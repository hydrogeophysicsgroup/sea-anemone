// Keep the 2D map flat and north-up: turn off MapLibre's rotate/tilt
// gestures (right-click drag, Ctrl+drag, two-finger rotate, keyboard).
// Plotly has no layout/config option for this, so it is done on the
// MapLibre map object Plotly creates (gd._fullLayout.map._subplot.map).
// Drawn lines are converted between screen and map coordinates assuming
// bearing = 0 and pitch = 0 (see map.py's paper2latlon), so a rotated
// map also breaks line drawing.
//
// Dash loads every .js file in assets/ automatically. Plotly can rebuild
// the MapLibre object when the figure is replaced, so this re-applies on
// every plotly_afterplot event and on a slow timer as a fallback.
(function () {
    function lockMap(gd) {
        var fullLayout = gd && gd._fullLayout;
        if (!fullLayout) { return; }
        Object.keys(fullLayout).forEach(function (key) {
            if (key.indexOf('map') !== 0) { return; }  // map, map2, ...
            var subplot = fullLayout[key] && fullLayout[key]._subplot;
            var map = subplot && subplot.map;
            if (!map || map._seaAnemoneLocked) { return; }
            if (map.dragRotate) { map.dragRotate.disable(); }
            if (map.touchZoomRotate) { map.touchZoomRotate.disableRotation(); }
            if (map.touchPitch) { map.touchPitch.disable(); }
            if (map.keyboard && map.keyboard.disableRotation) { map.keyboard.disableRotation(); }
            // Undo any rotation/tilt that happened before the lock applied.
            if (map.getBearing() !== 0 || map.getPitch() !== 0) {
                map.jumpTo({bearing: 0, pitch: 0});
            }
            // Block the context menu so a right-click does nothing at all.
            map.getCanvasContainer().addEventListener('contextmenu', function (e) { e.preventDefault(); });
            map._seaAnemoneLocked = true;
        });
    }

    function attach() {
        document.querySelectorAll('.js-plotly-plot').forEach(function (gd) {
            lockMap(gd);
            if (!gd._seaAnemoneNoRotate && typeof gd.on === 'function') {
                gd._seaAnemoneNoRotate = true;
                gd.on('plotly_afterplot', function () { lockMap(gd); });
            }
        });
    }

    setInterval(attach, 1000);
})();
