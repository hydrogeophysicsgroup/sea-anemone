from pandas import DataFrame
import pandas as pd
import numpy as np
import usf
import inspect
import torch
import os

def silence(s):
    pass

from anemone.inversion import LogResistivity
from anemone.inversion import fastJac, SCI

def make_log():
    from __main__ import sesh
    sesh.inv_status = []

    

def write_log(message):
    from __main__ import sesh
    sesh.inv_status.append(message)
    

def overview(temdf):
    df = temdf.pivot_table(
        index=['site_id'], 
        values=['date', 'daytime', 'latitude', 'longitude', 'elevation', 'utm_x', 'utm_y', 'distance'],
        aggfunc='first'
    )
    # We leave it as an index only for now to avoid ambiguity
    if 'misfit' in temdf.columns:
        misfit_means = temdf.groupby('site_id')['misfit'].mean()
        df['misfit'] = df.index.map(misfit_means)
    
    return df

def apply_slope_filter(temdf, threshold=1.0, min_points=8):
    """
    Disable datapoints after a large slope change in log-log space.

    Parameters
    ----------
    threshold : float
        Maximum allowed absolute change in slope between adjacent segments.
        If exceeded, all subsequent gates are disabled.
    min_points : int
        Minimum number of valid points required before slope checking begins.
    """

    if 'inuse_auto' not in temdf.columns:
        raise ValueError("Column 'inuse_auto' not found.")

    # Work per site and system
    grouped = temdf.groupby(['site_id', 'system_id'])

    for (site, system), df_grp in (temdf[temdf['system_id'] == 1].groupby(['site_id', 'system_id'])):

        df_grp = df_grp.sort_values('time')

        # Remove invalid rows
        df_valid = df_grp[
            (df_grp['dbdt'] > 0) &
            np.isfinite(df_grp['time']) &
            np.isfinite(df_grp['dbdt'])
        ]

        if len(df_valid) < min_points:
            continue

        log_t = np.log10(df_valid['time'].values)
        log_y = np.log10(np.abs(df_valid['dbdt'].values))

        # Compute segment slopes
        dt = np.diff(log_t)
        dy = np.diff(log_y)

        # Avoid divide-by-zero
        valid = dt != 0
        slopes = np.zeros_like(dy)
        slopes[valid] = dy[valid] / dt[valid]

        # Change in slope
        dslopes = np.abs(np.diff(slopes))

        # Find first large slope jump
        start_points = 9  # start checking after this many points

        # Index in dslopes corresponding to start_points
        start_idx = max(0, start_points - 2)

        # Only evaluate slope changes after enough points exist
        bad_idx = np.where(dslopes[start_idx:] > threshold)[0]

        if len(bad_idx) == 0:
            continue

        # Convert back to full index
        bad_idx = bad_idx[0] + start_idx

        # Index in original group where breakdown begins
        cutoff_local = bad_idx + 2  # +2 due to double diff
        cutoff_index = df_valid.index[cutoff_local]

        # Disable all later points
        mask = (temdf.index >= cutoff_index) & \
            (temdf['site_id'] == site) & \
            (temdf['system_id'] == system)

        temdf.loc[mask, 'inuse_manual'] = False

    return temdf

def apply_slope_filter(temdf, threshold=1.0, min_points=5):
    """
    Disable datapoints after a large slope change in log-log space.

    Parameters
    ----------
    threshold : float
        Maximum allowed absolute change in slope between adjacent segments.
        If exceeded, all subsequent gates are disabled.
    min_points : int
        Minimum number of valid points required before slope checking begins.
    """

    if 'inuse_auto' not in temdf.columns:
        raise ValueError("Column 'inuse_auto' not found.")

    # Work per site and system
    grouped = temdf.groupby(['site_id', 'system_id'])

    for (site, system), df_grp in (temdf[temdf['system_id'] == 1].groupby(['site_id', 'system_id'])):

        df_grp = df_grp.sort_values('time')

        # Remove invalid rows
        df_valid = df_grp[
            (df_grp['dbdt'] > 0) &
            np.isfinite(df_grp['time']) &
            np.isfinite(df_grp['dbdt'])
        ]

        if len(df_valid) < min_points:
            continue

        log_t = np.log10(df_valid['time'].values)
        log_y = np.log10(np.abs(df_valid['dbdt'].values))

        # Compute segment slopes
        dt = np.diff(log_t)
        dy = np.diff(log_y)

        # Avoid divide-by-zero
        valid = dt != 0
        slopes = np.zeros_like(dy)
        slopes[valid] = dy[valid] / dt[valid]

        # Change in slope
        dslopes = np.abs(np.diff(slopes))

        # Find first large slope jump
        bad_idx = np.where(dslopes > threshold)[0]

        if len(bad_idx) == 0:
            continue

        # Index in original group where breakdown begins
        cutoff_local = bad_idx[0] + 2  # +2 due to double diff

        cutoff_index = df_valid.index[cutoff_local]

        # Disable all later points
        mask = (temdf.index >= cutoff_index) & \
            (temdf['site_id'] == site) & \
            (temdf['system_id'] == system)

        temdf.loc[mask, 'inuse_manual'] = False

    return temdf

def from_usfzip(zip_path):
    with open(zip_path, 'rb') as f:
        zip_bytes = f.read()
    return from_zip_content(zip_bytes)

def from_zip_content(zip_content):
    import zipfile
    import io
    import base64

    if isinstance(zip_content, str):
        zip_bytes = base64.b64decode(zip_content)
    else:
        zip_bytes = zip_content

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        usf_files = [x for x in z.namelist() if x.endswith('.usf')]
        sweeps = []
        for i, fname in enumerate(usf_files):
            with z.open(fname, 'r') as f:
                new_sweeps = usf.Sweep.from_buffer(f, combine=False)
                if set([x.points for x in new_sweeps]) == {6,22}or set([x.points for x in new_sweeps]) == {20,27}:
                    sweeps += new_sweeps
                else:
                    print(f'Ignoring {fname} because it does not contain both low and high moment data.')                    
        return from_sweeps(sweeps, folder_path=z.namelist()[0]+'.zip')

def from_usf_folder(folder_path):
    sweeps = []
    usf_files = [folder_path+f for f in os.listdir(folder_path) if f.endswith('.usf')]
    for usf_file in usf_files:        
        with open(usf_file, 'rb') as f:
            print(f'Processing {usf_file}...')
            new_sweeps = usf.Sweep.from_buffer(f, combine=False)
            if set([x.points for x in new_sweeps]) == {6,22} or set([x.points for x in new_sweeps]) == {20,27}:
                sweeps += new_sweeps
            else:
                print(f'Ignoring {usf_file} because it does not contain both low and high moment data.')
    return from_sweeps(sweeps, folder_path=folder_path)

def from_sweeps(sweeps, folder_path=None):
    points = sorted(set([x.points for x in sweeps]))
    mega_sweeps = []
    for pnts in points:
        mega_sweeps.append(usf.Sweep.combine_sweeps([swp for swp in sweeps if swp.points==pnts]))
    
    mega_sweeps = sorted(mega_sweeps, key=lambda swp: np.nanmin(swp.time))
    try:
        lm,hm = mega_sweeps
    except:
        print(len(mega_sweeps))
        print(points)
        print(folder_path)

    n_sites,n_gates = lm.data.shape
    hm_initial_sign = np.nanmean(hm.data[:, :10], axis=1)

    # 2. Create a mask for sites where the average of first 10 gates is negative
    flip_mask = hm_initial_sign < 0

    # 3. Apply the flip to both lm and hm 2D arrays
    # This uses numpy broadcasting to flip all gates for the flagged sites
    lm.data[flip_mask] *= -1
    hm.data[flip_mask] *= -1

    print(f"Flipped signs for {np.sum(flip_mask)} sites based on HM polarity.")
    day_sort = np.argsort(lm.daytime)
    site_id = np.zeros(n_sites, dtype=int)
    site_id[day_sort] = np.arange(len(lm.daytime))

    data_avg = {
        'site_id': np.concatenate([np.ones(n_gates, dtype=int)*i for i in site_id]),
        'dbdt': lm.data.flatten(),
        'error':   lm.error.flatten(),
        'inuse_auto': [True for _ in lm.data.flatten()],
        'inuse_manual': [np.nan for _ in lm.data.flatten()],
        'time': lm.time.flatten(),
        'gate_id': np.concatenate([np.arange(n_gates) for i in site_id]),
        'system_id': [0 for _ in lm.data.flatten()],
        'date':     np.concatenate([np.ones(n_gates, dtype=int)*x for x in lm.date]),
        'latitude': np.concatenate([np.ones(n_gates, dtype=float)*x for x in lm.location[:, 1]]),
        'longitude':np.concatenate([np.ones(n_gates, dtype=float)*x for x in lm.location[:, 0]]),
        'elevation':np.concatenate([np.ones(n_gates, dtype=float)*x for x in lm.location[:, 2]]),
        'daytime':  np.concatenate([np.ones(n_gates, dtype=float)*x for x in lm.daytime]),
    }

    n_sites,n_gates = hm.data.shape

    data_avg['site_id']      = np.append(data_avg['site_id'], np.concatenate([np.ones(n_gates, dtype=int)*i for i in site_id]))
    data_avg['dbdt']         = np.append(data_avg['dbdt'], hm.data.flatten())
    data_avg['error']        = np.append(data_avg['error'], hm.error.flatten())
    data_avg['inuse_auto']   = np.append(data_avg['inuse_auto'], np.array([True for _ in hm.data.flatten()]))
    data_avg['inuse_manual'] = np.append(data_avg['inuse_manual'], np.array([np.nan for _ in hm.data.flatten()]))
    data_avg['time']         = np.append(data_avg['time'],      hm.time.flatten())
    data_avg['gate_id']      = np.append(data_avg['gate_id'],   np.concatenate([np.arange(n_gates) for i in range(n_sites)]))
    data_avg['system_id']    = np.append(data_avg['system_id'], np.array([1 for _ in hm.data.flatten()]))
    data_avg['date']         = np.append(data_avg['date'],      np.concatenate([np.ones(n_gates, dtype=int)*x for x in lm.date]))
    data_avg['latitude']     = np.append(data_avg['latitude'],  np.concatenate([np.ones(n_gates, dtype=float)*x for x in lm.location[:, 1]]))
    data_avg['longitude']    = np.append(data_avg['longitude'], np.concatenate([np.ones(n_gates, dtype=float)*x for x in lm.location[:, 0]]))
    data_avg['elevation']    = np.append(data_avg['elevation'], np.concatenate([np.ones(n_gates, dtype=float)*x for x in lm.location[:, 2]]))
    data_avg['daytime']      = np.append(data_avg['daytime'],   np.concatenate([np.ones(n_gates, dtype=float)*x for x in lm.daytime]))

    data_avg['daytime'] = data_avg['date']*100 + data_avg['daytime']
    forward_operators = usf.sweep2fwr(sweeps)


    df_data = DataFrame(data_avg)
    neg_mask = df_data['dbdt'] <= 0
    df_data.loc[neg_mask, 'inuse_manual'] = False
    df_data.sort_values(by=['site_id','system_id', 'gate_id'], inplace=True)
    df_data.reset_index(drop=True, inplace=True)
    
    df_data['error_lb'] = df_data['dbdt']-df_data['dbdt']/(1. + df_data['error']/100.)
    df_data['error_ub'] = df_data['dbdt']*(1. + df_data['error']/100.)-df_data['dbdt']

    df_data['log10_dbdt'] = np.log10(np.abs(df_data['dbdt']))

    df_data['sys_gate'] = df_data['system_id'] + df_data['gate_id']/1e6
    df_data['data_id'] = np.arange(len(df_data))
    import utm
    ok = ~np.isnan(df_data['latitude']) & ~np.isnan(df_data['longitude'])
    utmx,utmy,zone_number,zone_letter = utm.from_latlon(df_data['latitude'].values[ok], df_data['longitude'].values[ok])
    df_data['utm_x'] = np.nan
    df_data['utm_y'] = np.nan
    df_data['zone_number'] = np.nan
    df_data.loc[ok, 'utm_x'] = np.round(utmx, 1)
    df_data.loc[ok, 'utm_y'] = np.round(utmy, 1)
    df_data.loc[ok, 'zone_number'] = zone_number
    df_data.loc[ok, 'zone_letter'] = zone_letter
    ds = np.cumsum(np.sqrt(np.diff(utmx, prepend=utmx[0])**2 + np.diff(utmy, prepend=utmy[0])**2))
    df_data['distance'] = np.nan
    df_data.loc[ok, 'distance'] = np.round(ds, 1)
    df_data = apply_slope_filter(df_data, threshold=1.2)

    
    forward_operators[0].source     = forward_operators[1].source
    forward_operators[0].receiver   = forward_operators[1].receiver
    forward_operators[0].filterfunc = forward_operators[1].filterfunc     

    return df_data, forward_operators

def disable(temdf, data_ids):
    temdf['inuse_manual'] = temdf['inuse_manual'].mask(temdf['data_id'].isin(data_ids), False)
    return temdf

def enable(temdf, data_ids):
    temdf['inuse_manual'] = temdf['inuse_manual'].mask(temdf['data_id'].isin(data_ids), True)
    return temdf

@classmethod
def from_pandas(cls, dataframe, **kwargs):
    return cls(dataframe, **kwargs)

@classmethod
def load(cls, file_path):
    df = pd.read_csv(file_path)
    return cls.from_pandas(df)

def invert_individually(temdf, dmfwr, res_start, vc=0.4, hc=0.4, max_iterations=50):
    df_data = temdf.copy()
    df_overview = overview(df_data)

    # this gives a warning and may need to updated if pandas is updated to pandas 3.0
    df_data['include'] = df_data['inuse_manual'].astype(bool, copy=False).fillna(df_data['inuse_auto'])

    df_data['dbdt_syn'] = df_data['dbdt']*np.nan
    pivot_multi = df_data[(df_data['site_id']>-1)*(df_data['gate_id']>-1)].pivot_table(
        index=['site_id'],
        columns=['sys_gate'],
        values=['dbdt', 'error', 'include', 'data_id'],
    )
    pivot_multi['site_id'] = pivot_multi.index

    pivot_multi.columns = [f'{val}_{col}' for val, col in pivot_multi.columns]

    assert len(pivot_multi) == len(df_overview), "Expected 4 columns in pivot_multi"

    pivot_multi.sort_values(by='site_id', inplace=True)
    df_overview.sort_values(by='site_id', inplace=True)        
    results = []
    for i,((id_row, row), (id_meta, row_meta)) in enumerate(zip(pivot_multi.iterrows(), df_overview.iterrows())):
        assert id_meta == id_row, "Site ID mismatch between row and metadata"

        dbdt_values  = row.filter(like='dbdt_').values
        error_values = row.filter(like='error_').values
        include_values = row.filter(like='include_').values
        data_id = row.filter(like='data_id_').values

        d_obs = torch.from_numpy(dbdt_values).abs().log()
        d_err = torch.from_numpy(np.log1p(error_values/100.))
        include_mask = include_values.astype(bool)
        d_err[~include_mask] = torch.inf  # Set error to zero for included measurements

        inv = fastJac(d_obs, d_err, res_start, dmfwr, logger=print)
        inv.data_misfit_acceptance_threshold = 0.95
        res_mod = inv.invert(iter_cap=10)



        d_syn = inv.forward(*res_mod.mod).exp()
        df_data.loc[data_id, 'dbdt_syn'] = d_syn.numpy()

        rho,thick = res_mod.mod
        row_meta['site_id'] = id_meta
        row_meta['resistivity'] = rho.detach().cpu().numpy().tolist()
        row_meta['thickness'] = thick.detach().cpu().numpy().tolist()
        results.append(row_meta.to_dict())
        print(f'{i+1:02d} of {len(pivot_multi):02d}', flush=True, end='\r')

    df_resmod = pd.DataFrame(results)

    rows = []
    for _, row in df_resmod.iterrows():
        site_id = row['site_id']
        resistivities = row['resistivity']
        thicknesses = row['thickness']
        tops = np.concatenate([[0], np.cumsum(thicknesses)[:-1]])
        bottoms = np.cumsum(thicknesses)
        bottoms[-1] = bottoms[-1]*1.1
        for i, (rho, top, bottom) in enumerate(zip(resistivities, tops, bottoms)):
            rows.append({
                'site_id': site_id,
                'daytime': row['daytime'],
                'date': row['date'],
                'latitude': row['latitude'],
                'longitude': row['longitude'],
                'elevation': row['elevation'],
                'layer': i,
                'resistivity': rho,
                'top_depth': top,
                'bottom_depth': bottom,
                'center_depth': (top + bottom) / 2
            })

        df_layers = DataFrame(rows)
    return df_layers, df_data


def get_site_data(temdf, site_id):
    df_data     = temdf[temdf['site_id']==site_id].copy()
    df_data     = df_data[df_data['gate_id']>-1]
    df_data['include'] = df_data['inuse_manual'].astype(bool, copy=False).fillna(df_data['inuse_auto'].astype(bool))
    df_data.sort_values('data_id', inplace=True)
    dbdt=df_data['dbdt'].values
    d_obs = torch.from_numpy(np.abs(dbdt)).log()
    d_err = torch.from_numpy(np.log1p(df_data['error'].values/100))
    include_values = torch.from_numpy(df_data['include'].values.astype(bool))
    
    d_err[include_values==0] = torch.inf
    d_err[dbdt<0] = torch.inf
    return d_obs, d_err, df_data


def invert(temdf, dmfwr, res_start, vc=0.5, hc=0.8, max_iterations=50):
    make_log()
    df_data = temdf.copy()
    df_overview = overview(df_data)


    # this gives a warning and may need to updated if pandas is updated to pandas 3.0
    df_data['include'] = df_data['inuse_manual'].astype(bool, copy=False).fillna(df_data['inuse_auto'])

    df_data['dbdt_syn'] = df_data['dbdt']*np.nan
    pivot_multi = df_data[(df_data['site_id']>-1)*(df_data['gate_id']>-1)].pivot_table(
        index=['site_id'],
        columns=['sys_gate'],
        values=['dbdt', 'error', 'include', 'data_id'],
    )
    pivot_multi['site_id'] = pivot_multi.index
    
    pivot_multi.columns = [f'{val}_{col}' for val, col in pivot_multi.columns]

    assert len(pivot_multi) == len(df_overview), "Expected 4 columns in pivot_multi"

    pivot_multi.sort_values(by='site_id', inplace=True)
    df_overview.sort_values(by='site_id', inplace=True)        

    results  = []
    inv_list = []
    x_list,y_list = [],[]

    for i,((id_row, row), (id_meta, row_meta)) in enumerate(zip(pivot_multi.iterrows(), df_overview.iterrows())):
        assert id_meta == id_row, "Site ID mismatch between row and metadata"

        dbdt_values  = row.filter(like='dbdt_').values
        error_values = row.filter(like='error_').values
        include_values = row.filter(like='include_').values
        data_id = row.filter(like='data_id_').values

        d_obs = torch.from_numpy(dbdt_values).abs().log()
        d_err = torch.from_numpy(np.log1p(error_values/100.))
        include_mask = include_values.astype(bool)
        d_err[~include_mask] = torch.inf  # Set error to zero for included measurements

        inv = fastJac(d_obs, d_err, res_start.copy(), dmfwr.copy(), logger=silence)
        inv.setup_matrices()
        inv_list.append(inv)
        x_list.append(row_meta['utm_x'])
        y_list.append(row_meta['utm_y'])
    
    inv = SCI(inv_list, x=np.array(x_list), y=np.array(y_list), log=write_log)
    inv.reuse_jac = True
    inv.vertical_smoothness = vc
    inv.horizontal_smoothness = hc
    res_mods = inv.invert(iter_cap=max_iterations)

    # DOI: try to get from SCI, fall back to individual inversions, then 0
    if hasattr(inv, 'doi') and inv.doi is not None:
        doi = [x.item() if hasattr(x, 'item') else float(x) for x in inv.doi]
    else:
        doi = []
        for individual_inv in inv_list:
            if hasattr(individual_inv, 'doi') and individual_inv.doi is not None:
                val = individual_inv.doi
                doi.append(val.item() if hasattr(val, 'item') else float(val))
            else:
                doi.append(0.0)

    for i,((id_row, row), (id_meta, row_meta)) in enumerate(zip(pivot_multi.iterrows(), df_overview.iterrows())):
        assert id_meta == id_row, "Site ID mismatch between row and metadata"

        data_id = row.filter(like='data_id_').values    
        res_mod = res_mods[i].copy()

        d_syn = inv._dpredgrid[i].exp()
        df_data.loc[data_id, 'dbdt_syn'] = d_syn.numpy()
        
        
        rho,thick = res_mod.mod
        row_meta['site_id'] = id_meta
        row_meta['resistivity'] = rho.detach().cpu().numpy().tolist()
        row_meta['thickness'] = thick.detach().cpu().numpy().tolist()
        # row_meta['misfit'] = df_data.loc[data_id, 'misfit'].mean()
        row_meta['doi'] = doi[i]
        
        results.append(row_meta.to_dict())
        print(f'Inversion for data_id {i:02d} completed.')
    df_data['misfit'] = (((df_data['dbdt'] - df_data['dbdt_syn'])**2/(np.log1p(df_data['dbdt'].values*df_data['error'].values/100.)**2))**0.5)

    df_overview = overview(df_data)
    df_overview['doi'] = doi
    df_resmod = pd.DataFrame(results)

    rows = []
    for _, row in df_resmod.iterrows():
        site_id = row['site_id']
        resistivities = row['resistivity']
        thicknesses = row['thickness']
        tops = np.concatenate([[0], np.cumsum(thicknesses)[:-1]])
        bottoms = np.cumsum(thicknesses)
        for i, (rho, top, bottom) in enumerate(zip(resistivities, tops, bottoms)):
            rows.append({
                'site_id': site_id,
                'daytime': row['daytime'],
                'date': row['date'],
                'latitude': row['latitude'],
                'longitude': row['longitude'],
                'elevation': row['elevation'],
                'doi': doi[_],
                'layer': i,
                'resistivity': rho,
                'misfit': df_overview[df_overview.index==site_id]['misfit'].values[0],
                'top_depth': top,
                'bottom_depth': bottom,
                'center_depth': (top + bottom) / 2
            })
    

    df_layers = DataFrame(rows)
    return df_layers, df_data, df_overview


def invert_site(temdf, dmfwr, site_id, vc=0.4, res_start=100., max_iterations=20):
    t_max = max([fwr.times.max().item() for fwr in temdf.forward_operators])
    d_max = (t_max*4e6)**0.5
    n_layers = 30

    if res_start is None:
        thk = 1.+torch.logspace(-0.5, np.log10(d_max-n_layers+1), n_layers).diff()
        z = thk.cumsum()
        res_start=LogResistivity.smooth(torch.ones(n_layers)*40., z)

    elif isinstance(res_start, float):
        thk = 1.+torch.logspace(-0.5, np.log10(d_max-n_layers+1), n_layers).diff()
        z = thk.cumsum(0)
        res_start=LogResistivity.smooth(torch.ones(n_layers)*res_start, z)
    d_obs, d_err, df_site = get_site_data(temdf, site_id)

    inv1 = fastJac(d_obs, d_err, res_start, dmfwr)
    inv1.vertical_smoothness=vc

    res_mod=inv1.invert(iter_cap=max_iterations)
    doi_value = inv1.doi
    i,row = df_site.overview().iterrows().__next__()
    d_syn = inv1.data_predicted.exp()
    df_site.loc[:, 'dbdt_syn'] = d_syn.numpy()
    df_site['misfit'] = torch.sqrt(((d_obs - d_syn.log())**2/((d_err)**2)).mean())
    rho,thick = res_mod.mod
    rows = []
    tops = np.concatenate([[0], np.cumsum(thick)[:-1]])
    bottoms = np.cumsum(thick)
    for i, (rho, top, bottom) in enumerate(zip(rho, tops, bottoms)):
        rows.append({
            'site_id': df_site['site_id'].values[0],
            'daytime': row['daytime'],
            'date': row['date'],
            'latitude': row['latitude'],
            'longitude': row['longitude'],
            'elevation': row['elevation'],
            'misfit': df_site['misfit'].values[0],
            'doi': doi_value,
            'layer': i,
            'resistivity': rho,
            'top_depth': top,
            'bottom_depth': bottom,
            'center_depth': (top + bottom) / 2
        })
    df_layers = DataFrame(rows)
    return df_layers, df_site, inv1
