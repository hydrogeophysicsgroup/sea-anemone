// Show a loading cursor for as long as any Dash callback request is in
// flight. Dash callbacks all go through fetch() to the same
// "_dash-update-component" endpoint, so patching fetch here catches every
// callback app-wide without needing to touch the layout or list outputs.
(function () {
    if (window._loadingCursorPatched) return;
    window._loadingCursorPatched = true;

    let pending = 0;

    function setLoading(isLoading) {
        document.body.style.cursor = isLoading ? 'progress' : '';
    }

    const originalFetch = window.fetch;
    window.fetch = function (...args) {
        const url = args[0] instanceof Request ? args[0].url : args[0];
        const isDashCallback = typeof url === 'string' && url.includes('_dash-update-component');

        if (isDashCallback) {
            pending++;
            setLoading(true);
        }

        const result = originalFetch.apply(this, args);

        if (isDashCallback) {
            result.finally(() => {
                pending = Math.max(0, pending - 1);
                if (pending === 0) setLoading(false);
            });
        }

        return result;
    };
})();
