from typing import List
import pandas as pd
import json_numpy
from anemone.forwards import Forward
import temframe
from nosj import nosj
from basepanel import PanelSettings

from numpy import nan as np_nan, array as np_array

def rounded_nanmean(x):
    return round(x.mean(), 2)

@nosj
class SessionSettings:
    sub: PanelSettings = None

def clean_table(df):
    for col in df.columns:
        if col.startswith('_line'):
            del df[col]
    return df

@nosj
class Session:
    data:   pd.DataFrame = None
    models: pd.DataFrame = None
    site:   pd.DataFrame = None
    lines:  pd.DataFrame = None
    forwards: List[Forward] = None
    # Name for every instrument represented in `forwards`. Each instrument
    # contributes exactly 2 consecutive entries to `forwards` (low moment,
    # high moment), so instrument_names[i] pairs with forwards[2*i] and
    # forwards[2*i+1] -- this mirrors the system_id offsets used in `data`
    # (see usf_import.from_sweeps_multi). None/omitted means the legacy
    # single-instrument case: forwards is just [lm, hm].
    instrument_names: List[str] = None
    settings: SessionSettings = None
    save_dir: str = None

    boreholes : pd.DataFrame = None
    rock_map : dict      = None
    panel_ids: pd.DataFrame = None
    dem_path: str = None
    dem_name: str = None

    def __post_init__(self):
        self._dmfwr = None
        self._dmfwr_cache = {}

    @property
    def dmfwr(self):
        """
        Combined dual-moment forward operator for the single-instrument case.
        Kept for backwards compatibility. Raises if more than one instrument
        is loaded, since there's no longer one unambiguous forward operator
        to hand back -- use dmfwr_for(instrument_name) instead.
        """
        if self.instrument_names is not None and len(self.instrument_names) > 1:
            raise ValueError(
                f"Multiple instruments loaded ({self.instrument_names}) -- "
                "use dmfwr_for(instrument_name) instead of .dmfwr."
            )
        if self._dmfwr is None:
            self._dmfwr = self.forwards[0] + self.forwards[1]
        return self._dmfwr

    def dmfwr_for(self, instrument):
        """
        Combined dual-moment forward operator for one instrument.

        Looks up instrument's (lm, hm) pair in self.forwards via
        self.instrument_names and merges them with '+', same as the
        original single-instrument dmfwr did.
        """
        if self.instrument_names is None:
            if instrument is not None:
                raise ValueError(
                    "This session has no instrument_names set (single-instrument "
                    "session) -- use .dmfwr instead."
                )
            return self.dmfwr

        if instrument not in self._dmfwr_cache:
            i = self.instrument_names.index(instrument)
            self._dmfwr_cache[instrument] = self.forwards[2 * i] + self.forwards[2 * i + 1]
        return self._dmfwr_cache[instrument]

    def merge_upload(self, new_data, new_forwards, new_instrument_names):
        """
        Absorb one temframe.from_zip_content()-shaped (data, forwards,
        instrument_names) result into this session -- handles both the
        very first upload (self.data is None) and merging onto existing
        data, so callers never need an if/else.

        site_id/system_id/data_id are assigned fresh from 0 by
        temframe.from_sweeps_multi on every call, so two independently
        uploaded files collide on all three unless offset here. system_id
        is relied on elsewhere as `% 2 == 0` -> low moment / `== 1` ->
        high moment (panels.py, inversion_panels.py), so a reused
        instrument keeps its existing (even, even+1) block untouched, and
        a genuinely new instrument always lands on a fresh even offset.
        """
        if self.data is None:
            self.data = new_data
            self.forwards = list(new_forwards)
            self.instrument_names = list(new_instrument_names)
        else:
            new_data = new_data.copy()

            # site_id: offset past the current max (skip -1, the sentinel
            # used elsewhere for unassigned sites)
            site_offset = int(self.data['site_id'].max()) + 1
            mask = new_data['site_id'] != -1
            new_data.loc[mask, 'site_id'] = new_data.loc[mask, 'site_id'] + site_offset

            # data_id: always dense/unique, no sentinel
            data_offset = int(self.data['data_id'].max()) + 1
            new_data['data_id'] = new_data['data_id'] + data_offset

            if self.instrument_names is None:  # legacy single-instrument session
                self.instrument_names = ['__legacy__']

            # system_id: reuse an existing instrument's block (same
            # forwards, no duplicate instrument_names entry); allocate a
            # fresh even offset for a genuinely new instrument
            for idx_new, instrument_name in enumerate(new_instrument_names):
                old_offset = idx_new * 2
                if instrument_name in self.instrument_names:
                    new_offset = self.instrument_names.index(instrument_name) * 2
                else:
                    new_offset = len(self.instrument_names) * 2
                    self.instrument_names.append(instrument_name)
                    self.forwards.extend(new_forwards[idx_new * 2: idx_new * 2 + 2])

                if new_offset != old_offset:
                    rows = new_data['instrument'] == instrument_name
                    new_data.loc[rows, 'system_id'] = new_data.loc[rows, 'system_id'] - old_offset + new_offset
                    new_data.loc[rows, 'sys_gate'] = new_data.loc[rows, 'system_id'] + new_data.loc[rows, 'gate_id'] / 1e6

            self.data = pd.concat([self.data, new_data], ignore_index=True)
            self.data.sort_values(by=['site_id', 'system_id', 'gate_id'], inplace=True)
            self.data.reset_index(drop=True, inplace=True)

        self.data['include'] = self.data['inuse_manual'].astype(bool, copy=True).fillna(self.data['inuse_auto'])
        # Existing rows in self.data (and therefore self.models) keep their
        # original site_id -- only the newly-merged block above is offset --
        # so any prior inversion results remain valid and must NOT be
        # cleared here. The new sites simply have no rows in self.models
        # yet, same as any not-yet-inverted site.
        return self

    def save(self, folder=None, binary_threshold=100):
        self.update_site_table()
        other = self.copy()
        
        if folder is None and other.save_dir is None:
            from os import makedirs
            makedirs('anemone_backup', exist_ok=True)
            folder = 'anemone_backup/'
            other.save_dir = 'anemone_backup/'
            Warning('No folder specified for saving session, saving to default "anemone_backup/".')
        elif folder is None and other.save_dir is not None:
            folder = other.save_dir

        if other.data is not None:
            other.data = clean_table(other.data)
            other.data.to_csv(folder+'data.csv', index=False)
            other.data = 'data.csv'            
        if other.models is not None:
            other.models = clean_table(other.models)
            other.models.to_csv(folder+'models.csv', index=False)
            other.models = 'models.csv'
        if other.site is not None:
            other.site = clean_table(other.site)
            other.site.to_csv(folder+'site.csv', index=False)
            other.site = 'site.csv'                        
        if other.lines is not None:
            other.lines.to_csv(folder+'lines.csv', index=False)
            other.lines = 'lines.csv'    
        if other.boreholes is not None:
            print("boreholes to dataframe here")
            other.boreholes.to_csv(folder+'boreholes.csv', index=False)
            other.boreholes = 'boreholes.csv'
        if other.rock_map is not None:
            # Convert dict {"Clay": "#hex"} to DataFrame for saving
            df_rock = pd.DataFrame(list(other.rock_map.items()), columns=['RockType', 'Color'])
            df_rock.to_csv(folder + 'rock_map.csv', index=False)
            other.rock_map = 'rock_map.csv'


        if other.forwards is not None:
            for i in range(len(other.forwards)):
                other.forwards[i].save(folder + f'forward_{i}.json')
            other.forwards = [f'forward_{i}.json' for i in range(len(other.forwards))]

        other.__annotations__['data']   = str            
        other.__annotations__['site']   = str            
        other.__annotations__['models'] = str
        other.__annotations__['lines']   = str
        other.__annotations__['boreholes'] = str
        other.__annotations__['rock_map'] = str            
        other.__annotations__['forwards'] = List[str]
        res = json_numpy.dumps(other._to_nosj(binary_threshold=binary_threshold), indent=4)
        with open(folder+'session.json', 'wt') as f:
            f.write(res)        

    def load_dataframes(self):
        fwd_list = []
        if self.forwards is not None and isinstance(self.forwards, list):
            for fwd_path in self.forwards:
                fwd = Forward.load(self.save_dir+fwd_path).logify()
                fwd_list.append(fwd)
            self.forwards = fwd_list
        
        if self.data is not None and isinstance(self.data, str):
            self.data = pd.read_csv(self.save_dir+self.data)
            self.data['inuse_manual']=self.data['inuse_manual'].astype(bool)
            self.data['inuse_auto']=self.data['inuse_auto'].astype(bool)

        if self.models is not None and isinstance(self.models, str):
            self.models = pd.read_csv(self.save_dir+self.models)

        if self.boreholes is not None and isinstance(self.boreholes, str):
            df_flat = pd.read_csv(self.save_dir + self.boreholes)            
            from Sections_plotting import dataframe_to_boreholes
            self.borehole_list = dataframe_to_boreholes(df_flat)
            self.boreholes = df_flat
        if self.rock_map is not None and isinstance(self.rock_map, str):
            # This is the actual conversion step
            rock_df = pd.read_csv(self.save_dir + self.rock_map)
            self.rock_map = dict(zip(rock_df['RockType'], rock_df['Color']))


        if self.lines is not None and isinstance(self.lines, str):
            self.lines = pd.read_csv(self.save_dir+self.lines)
        self.update_site_table()


    @classmethod
    def from_folder(cls, folder):
        obj = cls.load(folder+'session.json')
        obj.save_dir = folder
        obj.load_dataframes()
        return obj

    @property
    def overview(self):
        self.site = self.update_site_table()
        return self.site        

    def update_site_table(self):
        site = None

        if self.data is not None:
            df = self.data.copy()
            df['include'] = df['inuse_manual'].astype(bool, copy=True).fillna(df['inuse_auto'])
            aggfunc = dict(                        
                        date=('date','first'),
                        daytime=('daytime','first'),
                        latitude=('latitude','first'),
                        longitude=('longitude','first'),
                        elevation=('elevation','first'),
                        utm_x=('utm_x','first'),
                        utm_y=('utm_y','first'),
                        distance=('distance','first'),
                        )
            if 'instrument' in df.columns:
                aggfunc['instrument'] = ('instrument', 'first')

            if 'misfit' in df.columns:
                aggfunc['misfit'] = ('misfit', rounded_nanmean)
                aggfunc['gates_used']=('include', 'sum')
                df.loc[df['include']==False, 'misfit'] = np_nan

            site = df.groupby('site_id', as_index=False).agg(**aggfunc)

            if self.models is not None:
                doi = self.models.groupby('site_id', as_index=False).agg(doi=('doi', 'first'))
                site = site.merge(doi, left_on='site_id', right_on='site_id', how='left')

        self.site = site
        self.line_update()
        return site
    
    def line_update(self):
        if self.lines is not None and self.data is not None:
            self.data   = clean_table(self.data)
            self.site   = clean_table(self.site)

            if self.models is not None: 
                self.models = clean_table(self.models)
            

            from map import Profile
            for line_id in self.lines.line.unique():
                c_line = self.lines[self.lines.line==line_id]
                x_axis,y_axis = f'_line_{line_id:0.0f}_x', f'_line_{line_id:0.0f}_y'
                lat, lon = c_line['latitude'].values, c_line['longitude'].values
                sec = Profile(lat, lon)
                self.lines.loc[self.lines.line==line_id, 'length'] = sec.cumulative_length
                self.lines.loc[self.lines.line==line_id, 'total_length'] = sec.length
                x,y = sec(self.site['latitude'].values, self.site['longitude'].values)
                self.site[x_axis] = x
                self.site[y_axis] = y
                if self.data is not None:
                    self.data = self.data.merge(self.site[[x_axis, y_axis]], left_on='site_id', right_index=True, how='left')
                if self.models is not None:
                    self.models = self.models.merge(self.site[[x_axis, y_axis]], left_on='site_id', right_index=True, how='left')
    

    @classmethod
    def from_workbench(cls, fname):
        import os
        import numpy as np

        base = fname
        # derive base stem if a specific workbench file was given
        for suffix in ('_dat.xyz', '_syn.xyz', '_inv.xyz'):
            if fname.endswith(suffix):
                base = fname[:-len(suffix)]
                break

        dat_path = base + '_dat.xyz'
        syn_path = base + '_syn.xyz'
        mod_path = base + '_inv.xyz'

        def read_workbench_table(path):
            import re
            from io import StringIO

            if not os.path.exists(path):
                raise FileNotFoundError(path)

            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            header_idx = None
            for i, line in enumerate(lines):
                s = line.strip()
                if not s:
                    continue
                if s.startswith('#'):
                    continue
                # prefer lines that contain likely column names
                tokens = re.split(r'\t|\s+', s)
                low = [t.lower() for t in tokens]
                if any(k in low for k in ('site_id', 'dbdt', 'dbdt_syn', 'latitude', 'layer', 'resistivity')):
                    header_idx = i
                    break

            if header_idx is None:
                # fallback to first non-empty non-comment line
                for i, line in enumerate(lines):
                    if line.startswith('/ LINE_NO '):
                        header_idx = i
                        break
                    # if line.strip() and not line.strip().startswith('#'):
                    #     header_idx = i
                    #     break

            text = ''.join([x.replace('/ ', '') for x in lines[header_idx:]])

            # try tab first, then whitespace
            try:
                df = pd.read_csv(StringIO(text), sep='\t')
                if df.shape[1] <= 1:
                    raise ValueError
            except Exception:
                df = pd.read_csv(StringIO(text), sep=r'\s+', engine='python')
            
            df['site_id'] = df.index

            return df


        def parse_gate_times(path):
            gates = None
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                line = f.readline()
                while not line.startswith('/GATE TIMES'):
                    line = f.readline()
                gates = [float(x) for x in f.readline()[1:].strip().split()]
            if gates is None:
                raise ValueError("Gate times not found in file")
            return gates

        def parse_epsg(path):
            epsg = None
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                line = f.readline()
                while 'epsg' not in line.lower():
                    line = f.readline()
                epsg = line.split(':')[1].strip()[:-1]
            if epsg is None:
                raise ValueError("EPSG not found in file")
            return epsg

        def epsg_to_utmzone(epsg):
            if isinstance(epsg, int):
                epsg = str(epsg)
            if epsg.startswith("326"):
                return int(epsg[3:]), 'N'
            elif epsg.startswith("327"):
                return int(epsg[3:]), 'S'
            else:
                raise ValueError("Invalid EPSG for UTM")

        times = parse_gate_times(dat_path)
        zone_number, zone_letter = epsg_to_utmzone(parse_epsg(dat_path))

        df_dat = read_workbench_table(dat_path)
        df_syn = read_workbench_table(syn_path)
        df_mod = read_workbench_table(mod_path)
        
            # convert placeholder 9999 to NaN and remove placeholder rows
        for df in (df_dat, df_syn, df_mod):
            try:
                df.replace(9999, np_nan, inplace=True)
            except Exception:
                pass
            # drop rows that are completely empty
            try:
                df.dropna(how='all', inplace=True)
            except Exception:
                pass
            # if site_id exists, drop rows where it's missing (placeholder)
            if 'site_id' in df.columns:
                try:
                    df.dropna(subset=['site_id'], inplace=True)
                except Exception:
                    pass

        # merge synthetic dbdt into measured data
        df1 = df_dat.copy()
        df_syn = df_syn.copy()


        # -------------------------
        # LOWERCASE COLUMNS
        # -------------------------
        df1.columns = df1.columns.str.lower()
        df_syn.columns = df_syn.columns.str.lower()

        # -------------------------
        # BUILD GATE MAPS
        # -------------------------
        gate_map = {f"data_{i+1}": times[i] for i in range(len(times))}
        std_map = {f"datastd_{i+1}": times[i] for i in range(len(times))}

        id_vars = ['site_id', 'x', 'y', 'date', 'time', 'elevation', 'segments']

        # -------------------------
        # RESHAPE OBSERVED DATA
        # -------------------------
        df_obs = df1.melt(
            id_vars=id_vars,
            value_vars=[c for c in df1.columns if c.startswith('data_') and not c.startswith('datastd')],
            var_name='gate',
            value_name='dbdt'
        )
        df_obs['time'] = df_obs['gate'].map(gate_map)

        df_std = df1.melt(
            id_vars=id_vars,
            value_vars=[c for c in df1.columns if c.startswith('datastd_')],
            var_name='gate',
            value_name='error_raw'
        )
        df_std['time'] = df_std['gate'].map(std_map)

        df_obs = df_obs.merge(
            df_std[['site_id', 'time', 'error_raw']],
            on=['site_id', 'time'],
            how='left'
        )

        # -------------------------
        # RESHAPE SYNTHETIC DATA
        # -------------------------
        df_syn_long = df_syn.melt(
            id_vars=id_vars,
            value_vars=[c for c in df_syn.columns if c.startswith('data_')],
            var_name='gate',
            value_name='dbdt_syn'
        )
        df_syn_long['time'] = df_syn_long['gate'].map(gate_map)

        # -------------------------
        # MERGE OBS + SYN
        # -------------------------
        df = df_obs.merge(
            df_syn_long[['site_id', 'time', 'dbdt_syn']],
            on=['site_id', 'time'],
            how='left'
        )

        # -------------------------
        # BUILD TARGET DF
        # -------------------------
        df_data = pd.DataFrame({
            'site_id': df['site_id'],
            'dbdt': df['dbdt'],
            'time': df['time'],
            'date': df['date'],
            'utm_x': df['x'],
            'utm_y': df['y'],
            'elevation': df['elevation'],
            'dbdt_syn': df['dbdt_syn'],
        })

        # system_id = numdata - 1
        df_data['system_id'] = df['segments'] - 1

        # error transformation
        df_data['error'] = (df['error_raw'] - 1.0) * 100.0
        del df['error_raw']

        # -------------------------
        # DERIVED COLUMNS
        # -------------------------
        df_data['error_lb'] = df_data['dbdt'] - df_data['dbdt'] / (1. + df_data['error'] / 100.)
        df_data['error_ub'] = df_data['dbdt'] * (1. + df_data['error'] / 100.) - df_data['dbdt']

        df_data['log10_dbdt'] = np.log10(df_data['dbdt'])

        # gate_id per site
        df_data['gate_id'] = df_data.groupby('site_id').cumcount()

        df_data['sys_gate'] = df_data['system_id'] + df_data['gate_id'] / 100.
        df_data['data_id'] = np.arange(len(df_data))

        # misfit
        df_data['misfit'] = df_data['dbdt'] - df_data['dbdt_syn']

        # flags
        df_data['inuse_auto'] = 1
        df_data['inuse_manual'] = 1
        df_data['include'] = 1
        df_data['daytime'] = 1
        df_data['zone_number'] = zone_number
        df_data['zone_letter'] = zone_letter


        df_data.replace(9999, np_nan, inplace=True)
        df_data = df_data[~df_data['dbdt'].isna()]

        # -------------------------
        # FINAL COLUMN ORDER
        # -------------------------
        df_data = df_data[
            ['site_id','dbdt','error','inuse_auto','inuse_manual','time',
            'gate_id','system_id','date','utm_x','utm_y','elevation',
            'daytime','error_lb','error_ub','log10_dbdt',
            'sys_gate','data_id','dbdt_syn','misfit','include',
            'zone_number','zone_letter']
        ]

        import utm
        lat,lon = utm.to_latlon(df_data['utm_x'].values, df_data['utm_y'].values, zone_number, zone_letter)
        df_data['latitude'] = lat
        df_data['longitude'] = lon

        df_data.sort_values(['site_id','system_id','gate_id'], inplace=True, kind='stable')
        df_data.reset_index(drop=True, inplace=True)

        df_data['misfit'] = (df_data['dbdt'] - df_data['dbdt_syn']).abs() / (df_data['dbdt'].abs() * df_data['error'] / 100.)
        df_data['distance'] = np.sqrt((df_data['utm_x'] - df_data['utm_x'].mean())**2 + (df_data['utm_y'] - df_data['utm_y'].mean())**2)

        # done
        df_data.head()

        system_time = []
        for system_id, group in df_data.groupby('system_id'):
            system_time.append(group['time'].unique())
        forwards = [Forward.example(times=stime, log_scale=True, do_setup=False) for stime in system_time]
        obj = cls()
        obj.data = df_data.copy()
        obj.forwards = forwards
        # Workbench files are always a single instrument's LM/HM (or more)
        # segments, so there's no separate instrument grouping to track --
        # leave instrument_names unset and let .dmfwr work as before.

        df = df_mod.copy()
        df.columns = df.columns.str.lower()

        # -------------------------
        # DETECT LAYERS DYNAMICALLY
        # -------------------------
        rho_cols = [c for c in df.columns if c.startswith('rho_') and not c.startswith('rho_std')]
        top_cols = [c for c in df.columns if c.startswith('dep_top_')]
        bot_cols = [c for c in df.columns if c.startswith('dep_bot_') and not c.startswith('dep_bot_std')]

        # sort properly (important!)
        rho_cols = sorted(rho_cols, key=lambda x: int(x.split('_')[-1]))
        top_cols = sorted(top_cols, key=lambda x: int(x.split('_')[-1]))
        bot_cols = sorted(bot_cols, key=lambda x: int(x.split('_')[-1]))

        id_vars = ['site_id','x','y','date','time','elevation','doi_standard']

        # -------------------------
        # MELT RESISTIVITY
        # -------------------------
        df_rho = df.melt(
            id_vars=id_vars,
            value_vars=rho_cols,
            var_name='layer',
            value_name='resistivity'
        )

        # -------------------------
        # MELT TOP DEPTH
        # -------------------------
        df_top = df.melt(
            id_vars=id_vars,
            value_vars=top_cols,
            var_name='layer',
            value_name='top_depth'
        )

        # -------------------------
        # MELT BOTTOM DEPTH
        # -------------------------
        df_bot = df.melt(
            id_vars=id_vars,
            value_vars=bot_cols,
            var_name='layer',
            value_name='bottom_depth'
        )

        # -------------------------
        # EXTRACT LAYER INDEX
        # -------------------------
        df_rho['layer'] = df_rho['layer'].str.extract('(\\d+)').astype(int) - 1
        df_top['layer'] = df_top['layer'].str.extract('(\\d+)').astype(int) - 1
        df_bot['layer'] = df_bot['layer'].str.extract('(\\d+)').astype(int) - 1

        # -------------------------
        # MERGE ALL
        # -------------------------
        df_long = df_rho.merge(
            df_top[['site_id','layer','top_depth']],
            on=['site_id','layer'],
            how='left'
        ).merge(
            df_bot[['site_id','layer','bottom_depth']],
            on=['site_id','layer'],
            how='left'
        )

        # -------------------------
        # BUILD TARGET
        # -------------------------
        df_data = pd.DataFrame({
            'site_id': df_long['site_id'],
            'date': df_long['date'],
            'utm_x': df_long['x'],
            'utm_y': df_long['y'],
            'elevation': df_long['elevation'],
            'doi': df_long['doi_standard'],
            'layer': df_long['layer'],
            'resistivity': df_long['resistivity'],
            'top_depth': df_long['top_depth'],
            'bottom_depth': df_long['bottom_depth'],
        })

        # -------------------------
        # DERIVED
        # -------------------------
        df_data['center_depth'] = (df_data['top_depth'] + df_data['bottom_depth']) / 2.0

        # placeholder misfit (no synthetic here unless you add it later)
        df_data['misfit'] = np.nan

        # flags / coords
        df_data['daytime'] = 1

        # UTM zone
        df_data['zone_number'] = zone_number
        df_data['zone_letter'] = zone_letter
        
        lat,lon = utm.to_latlon(df_data['utm_x'].values, df_data['utm_y'].values, zone_number, zone_letter)
        df_data['latitude'] = lat
        df_data['longitude'] = lon
        # -------------------------
        # OPTIONAL: LAT/LON (if needed)
        # -------------------------
        # (skipped for speed; can add utm.to_latlon vectorized if needed)

        # -------------------------
        # FINAL ORDER (matching your target)
        # -------------------------
        df_data = df_data[
            ['site_id','daytime','date',
            'utm_x','utm_y','elevation','doi',
            'layer','resistivity','misfit',
            'top_depth','bottom_depth','center_depth', 'latitude','longitude']
        ]

        df_data.head()    


        obj.models = df_data.copy()
        obj.models['site_id'] = obj.models['site_id'].astype(float)
        obj.save_dir = os.path.dirname(base) + os.sep if os.path.dirname(base) else ''

        # try to populate site table and lines
        try:
            obj.update_site_table()
        except Exception:
            pass

        return obj
