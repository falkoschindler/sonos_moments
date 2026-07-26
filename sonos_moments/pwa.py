from pathlib import Path

from fastapi.responses import JSONResponse
from nicegui import app, ui

THEME_COLOR = 'black'  # matches the header, so the status bar blends into the app

MANIFEST = {
    'id': '/',
    'name': 'Sonos Moments',
    'short_name': 'Moments',
    'description': 'Control Sonos speakers in a local network.',
    'start_url': '/',
    'scope': '/',
    'display': 'standalone',
    'background_color': 'white',
    'theme_color': THEME_COLOR,
    'icons': [
        {'src': '/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
        {'src': '/icon-512.png', 'sizes': '512x512', 'type': 'image/png'},
    ],
}


def setup() -> None:
    """Make the app installable on a phone's home screen and let it start without browser chrome.

    There is no service worker and no offline mode: without the home network the app cannot control
    anything anyway. That also keeps us clear of a dependency we could not satisfy - service workers
    require a secure context, and we are served over plain HTTP in the local network.
    """
    for size in (192, 512):
        # the icons are opaque on purpose: iOS composites a transparent home screen icon on black,
        # which would swallow the black circle of our logo
        app.add_static_file(local_file=Path(__file__).parent / f'icon-{size}.png', url_path=f'/icon-{size}.png')

    @app.get('/manifest.json')
    def manifest() -> JSONResponse:
        return JSONResponse(MANIFEST, media_type='application/manifest+json')

    ui.add_head_html(f'''
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="{THEME_COLOR}">
        <meta name="mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black">
        <meta name="apple-mobile-web-app-title" content="Moments">
        <link rel="apple-touch-icon" href="/icon-192.png">
    ''', shared=True)
