from typing import List
from pandas import DataFrame
import json_numpy
from anemone.forwards import Forward
import temframe
from nosj import nosj
from basepanel import PanelSettings

from numpy import nan as np_nan, array as np_array

import pandas as pd
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
    data:   DataFrame = None
    models: DataFrame = None
    site:   DataFrame = None
    lines:  DataFrame = None
    forwards: List[Forward] = None
    settings: SessionSettings = None
    save_dir: str = None

    boreholes : DataFrame = None
    rock_map : DataFrame = None
    panel_ids: DataFrame = None
    dem_path: str = None
    dem_name: str = None

    def __post_init__(self):
        self._dmfwr = None
    
    @property
    def dmfwr(self):
        if self._dmfwr is None:
            self._dmfwr = self.forwards[0] + self.forwards[1]
        return self._dmfwr


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
            other.boreholes.to_csv(folder+'boreholes.csv', index=False)
            other.boreholes = 'boreholes.csv'

        if other.rock_map is not None:
            other.rock_map.to_csv(folder+'rock_map.csv', index=False)
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
        