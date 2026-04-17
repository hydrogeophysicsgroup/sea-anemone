import csv
import numpy as np
import pandas as pd
import geopandas
# import pygmt
import xarray
import rioxarray
import utm
import concurrent.futures
from itertools import zip_longest
import time #just for testing

class mean_res:
    
    def __init__(self):
        #Define standard layer boundaries
        self.lyrbounds = []
        self.lyrbounds.append([0.,5.])
        self.lyrbounds.append([5.,10.])
        self.lyrbounds.append([10.,15.])
        self.lyrbounds.append([15.,20.])
        self.lyrbounds.append([20.,25.])
        self.lyrbounds.append([25.,30.])
        self.lyrbounds.append([30.,40.])
        self.lyrbounds.append([40.,50.])
        self.lyrbounds.append([50.,60.])
        self.lyrbounds.append([60.,70.])
        self.lyrbounds.append([70.,80.])
        self.lyrbounds.append([80.,90.])
        self.lyrbounds.append([100.,110.])
        self.lyrbounds.append([110.,120.])
        self.lyrbounds.append([120.,130.])
        self.lyrbounds.append([130.,140.])
        self.lyrbounds.append([140.,150.])
        self.lyrbounds.append([150.,175.])
        self.lyrbounds.append([175.,200.])
        self.epsg = 0
        self.nlyrs = 0
        self.nsites = 0

    # Read xyz model output from Workbench
    def read_WB_models(self,fname,**kwargs):
        verbose = kwargs.get('verbose',False)
        if verbose:
            print(f'Reading {fname}')
        # Get parameters from header
        with open(fname,'rt') as f:
            csvreader = csv.reader(f,delimiter='/')
            ii = 0
            try:
                for row in csvreader:
                    if row[1] == 'COORDINATE SYSTEM':
                        coordstr = csvreader.__next__()[1]
                        ii += 2
                        self.parse_EPSG(coordstr)
                        if verbose:
                            print(f'  EPSG: {self.epsg}')
                    elif row[1] == 'NUMBER OF LAYERS':
                        self.nlyrs = int(csvreader.__next__()[1])
                        if verbose:
                            print(f'  {self.nlyrs} layers')
                        ii += 2
                    elif row[1][0:8] == ' LINE_NO':
                        headers = row[1].split()
                        header_lines = ii + 1
                    else:
                        ii += 1
            except IndexError:
                pass
            cols = ['X','Y','RECORD','ELEVATION','RESDATA']
            dtps = ['float','float','int','float','float']
            for ii in range(self.nlyrs):
                cols.append(f'RHO_{int(ii+1)}')
                dtps.append('float')
            for ii in range(self.nlyrs):
                cols.append(f'DEP_TOP_{int(ii+1)}')
                dtps.append('float')
            for ii in range(self.nlyrs):
                cols.append(f'DEP_BOT_{int(ii+1)}')
                dtps.append('float')
            for ii in range(self.nlyrs):
                cols.append(f'THK_{int(ii+1)}')
                dtps.append('float')
            cols.append('DOI_STANDARD')
            dtps.append('float')
        col_idx = []
        for aa in cols:
            col_idx.append(headers.index(aa))
    
        #Because I used / as the delimiter, I need to close and open
        with open(fname,'rt') as f:
            #df = pd.read_csv(f,sep='\s+',header=header_lines-1,
            #    usecols=cols,dtype=dict(zip(cols,dtps)))
            df = pd.read_csv(f,sep=r'\s+',skiprows=header_lines-1,
                header=0,names=cols,usecols=col_idx)
        if verbose:
            print(f'  {len(df)} sites')
            print('  Done.')
            #print(df)

        return df

    # Convert WB models df to anemone data frame style
    def WB2Anemone(self,wbdf,**kwargs):
        verbose = kwargs.get('verbose',False)
        if verbose:
            print('Converting to Anemone data frame')
        self.nsites = wbdf.shape[0]
        self.epsg2utmzone()
        #if self.utmzone[1] == 'N':
        #    nort = True
        #else:
        #    nort = False
        
        latlon = wbdf.apply(lambda r: utm.to_latlon(r.X,r.Y,*self.utmzone),
            axis=1,result_type='expand')
        wbdf[['latitude','longitude']] = latlon

        res_colnames = [f'RHO_{ii}' for ii in range(1,self.nlyrs+1)]
        res_colnames_adj = [f'RHO_{ii:02d}'
            for ii in range(1,self.nlyrs+1)]
        dep_top_colnames = [f'DEP_TOP_{ii}' 
            for ii in range(1,self.nlyrs+1)]
        dep_top_colnames_adj = [f'DEP_TOP_{ii:02d}'
            for ii in range(1,self.nlyrs+1)]
        dep_bot_colnames = [f'DEP_BOT_{ii}'
            for ii in range(1,self.nlyrs+1)]
        dep_bot_colnames_adj = [f'DEP_BOT_{ii:02d}'
            for ii in range(1,self.nlyrs+1)]
        colnames = dict(zip(res_colnames+dep_top_colnames+
            dep_bot_colnames,res_colnames_adj+dep_top_colnames_adj+
            dep_bot_colnames_adj))

        if verbose:
            print('  Performing melt 0')
        df1 = wbdf.loc[:,['RECORD','latitude','longitude','ELEVATION',
            'X','Y']
            + res_colnames + dep_top_colnames + dep_bot_colnames+
            ['DOI_STANDARD']]\
            .rename(columns=colnames)\
            .melt(
            id_vars=['RECORD','latitude','longitude','ELEVATION','X','Y',
                'DOI_STANDARD'],
            value_vars=res_colnames_adj,
            var_name='res_id',
            value_name='resistivity'
        )

        if verbose:
            print('  Performing melt 1')
        df2 = wbdf.loc[:,['RECORD','latitude','longitude','ELEVATION',
            'X','Y']
            + res_colnames + dep_top_colnames + dep_bot_colnames +
            ['DOI_STANDARD']]\
            .rename(columns=colnames)\
            .melt(
            id_vars=['RECORD','latitude','longitude','ELEVATION','X','Y',
                'DOI_STANDARD'],
            value_vars=dep_top_colnames_adj,
            var_name='top_id',
            value_name='top_depth'
        )

        if verbose:
            print('  Performing melt 2')
        df3 = wbdf.loc[:,['RECORD','latitude','longitude','ELEVATION',
            'X','Y']
            + res_colnames + dep_top_colnames + dep_bot_colnames +
            ['DOI_STANDARD']]\
            .rename(columns=colnames)\
            .melt(
            id_vars=['RECORD','latitude','longitude','ELEVATION','X','Y',
                'DOI_STANDARD'],
            value_vars=dep_bot_colnames_adj,
            var_name='bottom_id',
            value_name='bottom_depth'
        )

        if verbose:
            print('  Merging melted dataframes')
        df4 = df1.join(df2.drop(columns=['RECORD','latitude',
            'longitude','ELEVATION','X','Y','DOI_STANDARD']), how='inner')
        df5 = df4.join(df3.drop(columns=['RECORD','latitude',
            'longitude','ELEVATION','X','Y','DOI_STANDARD']), how='inner')
        cntr = df5.apply(lambda r: self.calc_centre(r.top_depth,
            r.bottom_depth),
            axis=1,result_type='expand')
        df5['center_depth'] = cntr
        df5.rename(columns={'RECORD':'site_id','ELEVATION':'elevation',
            'res_id':'layer','X':'easting','Y':'northing',
            'DOI_STANDARD':'doi'},
            inplace=True)
        df5.drop(columns=['top_id','bottom_id'],inplace=True)
        lyrnm = df5.apply(lambda r: int(r.layer[4:])-1,axis=1,
            result_type='expand')
        df5['layer'] = lyrnm
        self.data = df5
        #_ = df5.apply(self.cullDOI,axis=1)
        if verbose:
            #print(df5.sort_values(by=['site_id','layer']))
            print('  Done.')
        return 0

    #Function for calculating centre location of layer
    def calc_centre(self,top_dep,bot_dep):
        return (top_dep+bot_dep)/2.

    #Parse out the EPSG number from the workbench output
    def parse_EPSG(self,epsg):
        self.epsg = int(epsg[epsg.find('epsg:')+5:-1])
        return 0

    #Set UTM zone from EPSG
    def epsg2utmzone(self):
        if int(str(self.epsg)[0:3]) == 326:
            ns = 'N'
        elif int(str(self.epsg)[0:3]) == 327:
            ns = 'S'
        else:
            raise ValueError
        self.utmzone = [int(str(self.epsg)[3:]),ns]
        return 0
        
    # Extract just one site and return new pandas frame
    def parseModel(self,mod,site_id,**kwargs):
        mod1 = mod[mod['site_id']==site_id]
        if kwargs.get('verbose') == True:
            print('Parsed site ' + str(site_id))
        return mod1

    # Return the layer index containing a given depth
    def getlyridx(self,mod,d,**kwargs):
        rw = mod[(mod['top_depth']<=d) & (mod['bottom_depth']>d)]
        #\TODO handle queries out of bounds
        return rw['layer'].item()

    # Return the proportion of the current layer above and below
    # the provided depth
    def getRatio(self,mod,d,lyr=None,**kwargs):
        if lyr is None:
            lyr = self.getlyridx(mod,d)
        mod1 = mod[mod['layer'] == lyr]
        depth = [mod1['top_depth'].item(),mod1['bottom_depth'].item()]
        props = []
        props.append((d - depth[0]) / (depth[1] - depth[0]))
        props.append((depth[1] - d) / (depth[1] - depth[0]))
        if kwargs.get('verbose'):
            print(f'Depth {d} esists in layer {lyr} with {props[0]:.1%}' +
                f' above and {props[1]:.1%} of the layer below.')
        return props

    # Return the mean resistivity of a depth interval
    def intMeanRes(self,mod,depthbounds,**kwargs):
        verbose = kwargs.get('verbose',False)
        method = kwargs.pop('MRmethod','horizontal').lower()
        lyrtop = self.getlyridx(mod,depthbounds[0],**kwargs)
        lyrbottom = self.getlyridx(mod,depthbounds[1],**kwargs)
        toprat = self.getRatio(mod,depthbounds[0],lyrtop,**kwargs)[1]
        bottomrat = self.getRatio(mod,depthbounds[1],lyrbottom,
            **kwargs)[0]
        ressum = 0.

        # Condition of entire interval within one layer
        if lyrtop == lyrbottom:
            if verbose:
                print(f'Depth {depthbounds} mean resistivity: ' +
                    f"{mod[mod['layer']==lyrtop]['resistivity'].item():.2f}" +
                    ' ohm.m')
            return mod[mod['layer'] == lyrtop]['resistivity'].item()

        # Weight each layer by thickness
        dpthweights = []
        for ii,a in enumerate(range(lyrtop,lyrbottom+1)):
            dpthweights.append(mod[mod['layer']==a]['bottom_depth'].item()-
                mod[mod['layer']==a]['top_depth'].item())
        dpthweights[0] *= toprat
        dpthweights[-1] *= bottomrat

        # Calculating horizontally is equivalent to the harmonic mean
        # Vertically is the arithmetic mean
        if method == 'horizontal':
            for ii,a in enumerate(range(lyrtop,lyrbottom+1)):
                ressum += dpthweights[ii] * \
                    (1./mod[mod['layer']==a]['resistivity'].item())
            mr = 1./(ressum/sum(dpthweights))
            if verbose:
                print(f'Depth {depthbounds} horizontal mean resistivity: '
                    + f'{mr:.2f} ohm.m')
            return mr
        elif method == 'vertical':
            for ii,a in enumerate(range(lyrtop,lyrbottom+1)):
                ressum += dpthweights[ii] * \
                    mod[mod['layer']==a]['resistivity'].item()
            mr = ressum / sum(dpthweights)
            if verbose:
                print(f'Depth {depthbounds} vertical mean resistivity:'
                    + f'{mr:.2f} ohm.m')
            return mr

    # Return the mean resistivities for a single site from a list
    # of depth intervals
    def meanRes_site(self,**kwargs):
        mr = []
        sid = int(kwargs.pop('site_id',0))
        mod1 = self.parseModel(self.data,sid,**kwargs)
        for ii,a in enumerate(self.lyrbounds):
            mr.append(self.intMeanRes(mod1,a,**kwargs))
        return mr

    # Helper function for process pool executor
    def mrsite_threads(self,site,logres=True):
        m1 = self.data[self.data['site_id']==site]
        m2 = m1[m1['layer']==0]
        loc = [site,m2['latitude'].item(),m2['longitude'].item(),
            m2['elevation'].item(),m2['easting'].item(),
            m2['northing'].item(),m2['doi'].item()]
        if logres:
            mr = np.log10(self.meanRes_site(site_id=site))
        else:
            mr = self.meanRes_site(site_id=site)
        self.tmptable.append([*loc,*mr])
        return [*loc,*mr]

    # Second helper function
    def mrsite_threadsgroup(self,sites,logres=True):
        tbl = []
        cleansites = [site for site in sites if site is not None]
        for site in cleansites:
            tbl.append(self.mrsite_threads(site))
        
        return tbl


    def meanRes(self,**kwargs):
        verbose = kwargs.pop('verbose',False)
        logres = kwargs.pop('logres',True)
        nproc = kwargs.pop('nproc',1)
        sites = self.data['site_id'].unique()
        if verbose:
            print(f'Computing mean resistivities for {len(sites)} sites')
        tabl = []
        nsites = len(sites)
        t = time.time()
        if nproc > 1:
            if verbose:
                print(f'  with {nproc} threads...')
            self.tmptable = []
            with concurrent.futures.ProcessPoolExecutor(nproc) as executor:
                results = [executor.submit(self.mrsite_threadsgroup, group,
                    logres) for group in grouper(sites, 70)]
                for aa in concurrent.futures.as_completed(results):
                    for bb in aa.result():
                        tabl.append(bb)
            #executor = concurrent.futures.ProcessPoolExecutor(nproc)
            #futures = [executor.submit(self.mrsite_threads, group)
            #    for group in grouper(sites, 20)]
            #concurrent.futures.wait(futures)
            #tabl = self.tmptable
        else:
            for ii,a in enumerate(sites):
                # This is a little dirty
                m1 = self.data[self.data['site_id']==a]
                m2 = m1[m1['layer']==0]
                loc = [a,m2['latitude'].item(),m2['longitude'].item(),
                    m2['elevation'].item(),m2['easting'].item(),
                    m2['northing'].item(),m2['doi'].item()]
                if logres:
                    mr = np.log10(self.meanRes_site(site_id=a,**kwargs))
                else:
                    mr = self.meanRes_site(site_id=a,**kwargs)
                tabl.append([*loc,*mr])
                if verbose:
                    #print(f'  {ii} / {nsites} sites', end='\r')
                    printProgressBar(ii+1,nsites,length=35)
        print(f'  Execution took {time.time()-t} seconds.') 
        cols2 = []
        for ii in range(0,len(tabl[0])-7):
            cols2.append(f'RHO_{ii}')
        self.paramcols = cols2
        self.mrdf = pd.DataFrame(tabl,columns=[*['site_id',
            'latitude','longitude','elevation','easting',
            'northing','doi'],*cols2])
        #print(self.mrdf)
        if verbose:
            print('  Masking DOI')
        self.mrdf = self.mrdf.apply(self.cullDOI,axis=1)
        if verbose:
            print('  Done.')
        return 0

    #Cull all data below DOI
    def cullDOI(self,r):
        doi = r['doi']
        #print(doi)
        #print(np.array(self.lyrbounds)[:,1])
        x = np.where(np.array(self.lyrbounds)[:,1] > doi)
        #print(x[0])
        #print(len(x[0]))
        cols = []
        if len(x[0]) > 0:
            for a in x[0]:
                r[f'RHO_{a}'] = np.nan
            return r
        else:
            return r

                            
            
        

class grid_res:
    
    def __init__(self,df,utmepsg,verbose='False',geocrs='epsg:4326',
        paramcols=[],lyr=[]):
        if lyr == []:
            self.lyr = []
            self.lyr.append([0.,5.])
            self.lyr.append([5.,10.])
            self.lyr.append([10.,15.])
            self.lyr.append([15.,20.])
            self.lyr.append([20.,25.])
            self.lyr.append([25.,30.])
            self.lyr.append([30.,40.])
            self.lyr.append([40.,50.])
            self.lyr.append([50.,60.])
            self.lyr.append([60.,70.])
            self.lyr.append([70.,80.])
            self.lyr.append([80.,90.])
            self.lyr.append([100.,110.])
            self.lyr.append([110.,120.])
            self.lyr.append([120.,130.])
            self.lyr.append([130.,140.])
            self.lyr.append([140.,150.])
            self.lyr.append([150.,175.])
            self.lyr.append([175.,200.])
        else:
            self.lyr = lyr
        self.grids = []
        self.verbose = verbose
        self.crs = geocrs
        self.epsg = utmepsg
        if paramcols == []:
            for a in df.columns:
                if a[-1].isnumeric():
                    self.paramcols.append(a)
        else:
            self.paramcols = paramcols
        self.utmcrs = [int(str(utmepsg)[3:]),'N']
        if str(utmepsg)[0:3] == '327':
            self.utmcrs[1] = 'S'
        self.mean_params = df

    @classmethod
    def from_WB_models(cls,fname,**kwargs):
        verbose = kwargs.pop('verbose',False)
        savepickle = kwargs.pop('savepickle',False)
        mr = mean_res()
        wbdf = mr.read_WB_models(fname,verbose=verbose)
        mr.WB2Anemone(wbdf,verbose=verbose)
        mr.meanRes(verbose=verbose,**kwargs)
        if savepickle is not False:
            mr.mrdf.to_pickle(savepickle)
            if verbose:
                print(f'Mean resistivities saved to {savepickle}.')
        
        return cls(mr.mrdf,mr.epsg,verbose=verbose,geocrs='epsg:4326',
            paramcols=mr.paramcols)

    @classmethod
    def from_pickle(cls,fname,picklename,**kwargs):
        verbose = kwargs.get('verbose',False)
        if verbose:
            print(f'Reading {picklename}')
        mr = mean_res()
        wbdf = mr.read_WB_models(fname,verbose=verbose)
        mr.mrdf = pd.read_pickle(picklename)
        paramcols = []
        for a in mr.mrdf.columns:
            #if a[0:3] == 'RHO':
            if a[-1].isnumeric():
                paramcols.append(a)
        if verbose:
            print('  Done importing mean resistivity dataframe.')

        return cls(mr.mrdf,mr.epsg,verbose=verbose,geocrs='epsg:4326',
            paramcols=paramcols)

    def define_georegion(self,**kwargs):
        padding = kwargs.pop('padding',0.05)
        minx = np.min(self.mean_params.easting)
        maxx = np.max(self.mean_params.easting)
        xrng = maxx - minx
        minx = minx - (padding*xrng)
        maxx = maxx + (padding*xrng)
        miny = np.min(self.mean_params.northing)
        maxy = np.max(self.mean_params.northing)
        yrng = maxy - miny
        miny = miny - (padding*yrng)
        maxy = maxy + (padding*yrng)
        georegsw = utm.to_latlon(minx,miny,self.utmcrs[0],
            self.utmcrs[1])
        georegne = utm.to_latlon(maxx,maxy,self.utmcrs[0],
            self.utmcrs[1])
        self.geo_region = [georegsw[1],georegne[1],\
            georegsw[0],georegne[0]]
        self.proj_region = f'{np.floor(minx):.0f}/{np.ceil(maxx):.0f}/'\
            f'{np.floor(miny):.0f}/{np.ceil(maxy):.0f}'
        self.xrng = xrng
        self.yrng = yrng
        self.grid_convergence()
        xreg2 = [utm.from_latlon(georegsw[0],georegsw[1])[0],
            utm.from_latlon(georegne[0],georegne[1])[0],
            utm.from_latlon(georegsw[0],georegsw[1])[1],
            utm.from_latlon(georegne[0],georegne[1])[1]]
        xreg2[1] += np.sin((self.CA*np.pi)/180.)*(maxx-minx)
        xreg2[0] -= np.sin((self.CA*np.pi)/180.)*(maxx-minx)
        xreg2[3] -= np.sin((self.CA*np.pi)/180.)*(maxy-miny)*0.5
        self.proj_region_CA = xreg2
        georegswCA = utm.to_latlon(xreg2[0],xreg2[2],self.utmcrs[0],
            self.utmcrs[1])
        georegneCA = utm.to_latlon(xreg2[1],xreg2[3],self.utmcrs[0],
            self.utmcrs[1])
        self.geo_region_CA = [georegswCA[1],georegneCA[1],\
            georegswCA[0],georegneCA[0]]
    
    def grid_param(self,param_column,spacing,**kwargs):
        ex_radius = kwargs.pop('ex_radius','4c')
        tension = kwargs.pop('tension',0.25)
        #t = self.mean_params.drop(self.mean_params[np.isnan(
        #    self.mean_params[param_column])].index,inplace=False)
        t = self.mean_params[~np.isnan(self.mean_params[param_column])]
        #meangrid = pygmt.blockmean(data=self.mean_params[['easting',
        meangrid = pygmt.blockmean(data=t[['easting',
            'northing',param_column]],spacing=spacing,
            region=self.proj_region)
        grid = pygmt.surface(data=meangrid[['easting','northing',
            param_column]],spacing=spacing,
            region=self.proj_region,maxradius=ex_radius,
            tension=f'i{tension}b0') #'i0.99b0')
        return grid

    def grid_parameters(self,**kwargs):
        spacing = str(kwargs.pop('spacing','50')) + '+e'
        verbose = kwargs.get('verbose',False)
        gdf_geographic = geopandas.GeoDataFrame(self.mean_params,
            geometry=geopandas.points_from_xy(
            self.mean_params.latitude,self.mean_params.longitude),
            crs=self.crs)
        self.define_georegion(**kwargs)
        if verbose:
            print(f'Gridding {len(self.paramcols)} surfaces.')
        for ii,a in enumerate(self.paramcols):
            self.grids.append(self.grid_param(param_column=a,
                spacing=spacing,**kwargs))
            if verbose:
                printProgressBar(ii+1,len(self.paramcols),length=35)

    def grid_convergence(self):
        cm = (self.utmcrs[0]*6) - 183
        phi = (self.geo_region[3] + self.geo_region[2])/2. #lon
        lam = (self.geo_region[1] + self.geo_region[0])/2. #lat
        self.CA = (lam - cm) * np.sin((phi*np.pi)/180.)

    def grid_in_latlon(self,grid):
        x = grid['x'].to_numpy()
        y = grid['y'].to_numpy()
        [X,Y] = np.meshgrid(x,y)
        LON = np.zeros(X.shape)
        LAT = np.zeros(Y.shape)
        [LAT,LON] = utm.to_latlon(X,Y,self.utmcrs[0],self.utmcrs[1])
        lat = LAT[:,0]
        lon = LON[0,:]
        return grid.assign_coords(x=lon,y=lat)

    def create_map(self,grididx,**kwargs):
        verbose = kwargs.get('verbose',False)
        vminmax = kwargs.pop('vminmax',[0,3])
        plot_points = kwargs.pop('plot_points',True)
        figwidth = kwargs.pop('figwidth','10')
        proj = f'M{figwidth}c'
        scalebar = kwargs.pop('scalebar',True)
        scalebar_loc = kwargs.pop('scalebar_loc','TL').upper()
        FONT_TITLE = str(kwargs.pop('FONT_TITLE',12))+'p'
        FONT_ANNOT_PRIMARY = int(kwargs.pop('FONT_ANNOT_PRIMARY',10))
        cbarfont = str(int(np.round(FONT_ANNOT_PRIMARY*1.5)))+'p'
        FONT_ANNOT_PRIMARY = str(FONT_ANNOT_PRIMARY)+'p'
        tilezoom = int(kwargs.pop('tilezoom',14))
        cmap = kwargs.pop('cmap','wysiwyg')
        fname = kwargs.pop('fname','./plotmrm.png')
        if verbose:
            print(f'  Printing layer {self.lyr[grididx][0]}m to '+\
                f'{self.lyr[grididx][1]}m depth')
            print(f'   Colourscale limits: {vminmax}')
            print(f'   Figure width: {figwidth}')
            print(f'   Projection: {proj}')
            print(f'   Scalebar location: {scalebar_loc}')



        fig = pygmt.Figure()
        pygmt.config(MAP_ANNOT_OBLIQUE='lat_parallel')
        pygmt.config(MAP_ANNOT_ORTHO='E')
        pygmt.config(FONT_ANNOT_PRIMARY=FONT_ANNOT_PRIMARY)
        pygmt.config(FONT_TAG=FONT_ANNOT_PRIMARY)
        pygmt.config(FONT_TITLE=FONT_TITLE)
        fig.tilemap(zoom=tilezoom,region=self.geo_region,projection=proj,
            source='http://www.google.cn/maps/vt?lyrs=s@189&gl=cn&x={x}&y={y}&z={z}',
            frame=[f'WS+tMean Resistivity {self.lyr[grididx][0]}m to'+\
            f' {self.lyr[grididx][1]}m Depth','afg'])
        pygmt.makecpt(cmap=cmap,series=vminmax)
        fig.grdimage(grid=self.grid_in_latlon(self.grids[grididx]),
            cmap=True,nan_transparent=True,projection=proj,
            region=self.geo_region)
        with pygmt.config(FONT_ANNOT_PRIMARY=cbarfont,
            FONT_ANNOT_SECONDARY=cbarfont,
            FONT_LABEL=cbarfont):
            fig.colorbar(
                frame="x+lLog Resistivity [log@[_{10}@[(@[\\Omega@[ m)]")

        if scalebar:
            if self.xrng < 5000. and self.xrng >= 1000:
                b = np.round(self.xrng * 0.3 * 0.01) * 100.
                barwidth = f'{b:.0f}e'
            elif self.xrng >= 5000:
                #barwidth = str(self.xrng * 0.3 *0.001) + 'k'
                b = np.round(self.xrng * 0.3 * 0.01) * 100.
                barwidth = f'{b:.0f}e'
            else:
                b = np.round((self.xrng * 0.3)/50.) * 50.
                barwidth = f'{b:.0f}e'
                
            pos = f'j{scalebar_loc}+j{scalebar_loc}+o0.8c/0.3c'

            fig.basemap(region=self.geo_region,
                map_scale=f'{pos}+w{barwidth}+f+u',projection=proj,
                box='+gwhite@30+p0.5p,gray30,solid+r3p')

        if plot_points:
            fig.plot(
                x=self.mean_params.longitude,
                y=self.mean_params.latitude,
                fill="black",style="c0.2c")

        fig.savefig(fname,crop=True,dpi=300)
        return 0

    def create_all_maps(self,**kwargs):
        verbose = kwargs.pop('verbose',False)
        if verbose:
            print('Printing maps to file')
        for ii,a in enumerate(self.grids):
            if verbose:
                print(f'{ii+1} of {len(self.grids)}')
                printProgressBar(ii+1,len(self.grids),length=35)
            self.create_map(ii,fname=f'./{ii}mrm.png',verbose=False,
                **kwargs)

# https://stackoverflow.com/a/15143994/1984620
# https://docs.python.org/3/library/itertools.html#recipes
def grouper(iterable, n, *, incomplete='fill', fillvalue=None):
    "Collect data into non-overlapping fixed-length chunks or blocks."
    # grouper('ABCDEFG', 3, fillvalue='x')       → ABC DEF Gxx
    # grouper('ABCDEFG', 3, incomplete='strict') → ABC DEF ValueError
    # grouper('ABCDEFG', 3, incomplete='ignore') → ABC DEF
    iterators = [iter(iterable)] * n
    match incomplete:
        case 'fill':
            return zip_longest(*iterators, fillvalue=fillvalue)
        case 'strict':
            return zip(*iterators, strict=True)
        case 'ignore':
            return zip(*iterators)
        case _:
            raise ValueError('Expected fill, strict, or ignore')        

# I got this on stack overflow but I cannot find it again so I do not
# know who to credit.  I sincerely apologise for that!
def printProgressBar(iteration, total, prefix='',suffix='',decimals=1,
    length=50,fill='\u2589',printEnd='\r'):
    
    percent = ("{0:."+str(decimals)+"f}").format(100*
        (iteration/float(total)))
    filledLength = int(length*iteration // total)
    bar = fill * filledLength + '-' * (length - filledLength)
    print(f'\r{prefix} |{bar}| {percent}% {suffix}',end=printEnd)
    if iteration == total:
        print()

if __name__ == '__main__':

    verbose = True
    ## Test of mean resistivity calculation
    mr = mean_res()
    wbdf = mr.read_WB_models('Models/Combined_mod.xyz',verbose=verbose)
    mr.WB2Anemone(wbdf,verbose=verbose)
    mr.meanRes(verbose=verbose,logres=True,MRmethod='horizontal')

    ##mr.mrdf.to_pickle('./mr.pkl')
    #mr.mrdf = pd.read_pickle('./mr.pkl')

    ## Example of calling mean res calc directly from plot_res
    gr = grid_res.from_WB_models('../Models/Combined_mod.xyz',
        verbose=verbose,logres=True,MRmethod='horizontal',
        savepickle=False,nproc=16)

    ## Example of using a saved pickle
    #gr = grid_res.from_pickle('../Models/Combined_mod.xyz','./mr.pkl',
    #    verbose=verbose)

    ## Grid the data once loaded
    gr.grid_parameters(padding=0.1,spacing=25,verbose=verbose,
        tension=0.1)

    ## Plot all
    gr.create_all_maps(verbose=verbose,plot_points=False,tilezoom=17,
        FONT_TITLE=14,vminmax=[0,2.47],figwidth=10,scalebar=True,
        scalebar_loc='TL',FONT_ANNOT_PRIMARY=10,cmap='wysiwyg')
    
