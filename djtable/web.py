"""LAN sample manager; independent process so HTTP never runs in audio callbacks."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import logging
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit, parse_qs

from .__main__ import read_config
from .library import Library, SLOTS, MAX_UPLOAD, MAX_DECODED


class SampleServer(ThreadingHTTPServer):
    """Bound in-flight uploads/previews to fit the Zero 2 W's small memory."""
    def __init__(self, *args, **kwargs):
        # A page loads CSS and three scripts together; three slots could reject
        # a script permanently, leaving its selector stuck on "Connecting".
        self.connections = threading.BoundedSemaphore(8)
        self.uploads = threading.BoundedSemaphore(2)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.0 503 Busy\r\nContent-Length: 0\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()


def handler_for(library, sample_root=None, modes=None):
    from .activities import Activities, ACTIVITIES
    activities = Activities(modes.root if modes else library.root.parent)
    from .settings import WebControls
    controls = WebControls(modes.root if modes else library.root.parent)
    token = secrets.token_hex(24)
    default_library = library

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def allowed_host(self):
            host = urlsplit('http://' + self.headers.get('Host', '')).hostname
            if host in ('localhost', 'pi-pi', 'pi-pi.local'):
                return True
            try:
                address = ipaddress.ip_address(host or '')
                return address.is_private or address.is_loopback
            except ValueError:
                return False

        def send_data(self, status, body, content_type='application/json'):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            try:
                if not self.allowed_host():
                    self.send_data(403, {'error': 'Use the Pi local IP address'})
                    return
                route = urlsplit(self.path).path
                mode = modes.validate(parse_qs(urlsplit(self.path).query).get('mode', [modes.selected()])[0]) if modes else 'teenage_disco'
                library = modes.library(mode) if modes else default_library
                if route == '/api/wifi':
                    from .wifi import request
                    self.send_data(200, request({'action': 'status'}))
                elif route == '/api/status':
                    from .status import read_status
                    self.send_data(200, read_status())
                elif route == '/api/modes':
                    from .modes import MODES
                    from .status import read_status
                    status = read_status()
                    self.send_data(200, {'modes': MODES, 'selected': modes.selected() if modes else mode,
                                         'runtime': status.get('mode') if status.get('online') else None, 'csrf': token})
                elif route == '/api/activities':
                    from .status import read_status
                    status = read_status()
                    self.send_data(200, {'activities': ACTIVITIES, 'selected': activities.selected(),
                                         'runtime': status.get('activity') if status.get('online') else None,
                                         'recording': status.get('recording') if status.get('online') else None, 'bluetooth': status.get('bluetooth') if status.get('online') else None,
                                         'maker_settings': activities.maker_settings(), 'csrf': token})
                elif route == '/api/library':
                    from .modes import MODES
                    state = library.read()
                    if modes:
                        state['assignments'].update({slot: item for slot, item in modes.library('teenage_disco').read()['assignments'].items()
                                                     if slot.startswith(('colours/', 'symbols/'))})
                    manifest = Path(__file__).resolve().parents[1] / 'assets/speech/manifest.json'
                    words = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else []
                    self.send_data(200, dict(state, mode=mode, tones=MODES[mode]['tones'], csrf=token, slots=SLOTS, words=words, max_decoded_bytes=MAX_DECODED))
                elif route.startswith('/word/') and sample_root is not None:
                    slot = route.removeprefix('/word/')
                    if slot not in SLOTS or not slot.startswith(('colours/', 'symbols/')):
                        self.send_data(404, {'error': 'Word not found'})
                    else:
                        library = modes.library('teenage_disco') if modes else library
                        assignment = library.read()['assignments'].get(slot)
                        path = library.path(assignment['file']) if assignment else Path(sample_root) / slot
                        self.send_data(200, path.read_bytes(), 'audio/wav')
                elif route in ('/instrument/piano.wav', '/instrument/high.wav', '/instrument/synth.wav'):
                    path = Path(__file__).resolve().parents[1] / 'assets/instruments'
                    if mode != 'teenage_disco':
                        path = path / mode
                    path = path / route.rsplit('/', 1)[1]
                    self.send_data(200, path.read_bytes(), 'audio/wav')
                elif route.startswith('/audio/'):
                    filename = route.removeprefix('/audio/')
                    if modes and filename in {item['file'] for slot, item in modes.library('teenage_disco').read()['assignments'].items()
                                              if slot.startswith(('colours/', 'symbols/'))}:
                        library = modes.library('teenage_disco')
                    if filename not in {i['file'] for i in library.items(library.read())}:
                        self.send_data(404, {'error': 'Sample not found'})
                    else:
                        self.send_data(200, library.path(filename).read_bytes(), 'audio/wav')
                elif route in ('/wifi', '/wifi.js'):
                    name = 'wifi.html' if route == '/wifi' else 'wifi.js'
                    mime = 'text/html; charset=utf-8' if route == '/wifi' else 'text/javascript; charset=utf-8'
                    self.send_data(200, (Path(__file__).parent / 'static' / name).read_bytes(), mime)
                elif route in ('/', '/admin', '/admin/', '/app.js', '/upload.js', '/modes.js', '/activities.js', '/style.css'):
                    name = {'/': 'index.html', '/admin': 'admin.html', '/admin/': 'admin.html', '/app.js': 'app.js', '/upload.js': 'upload.js', '/modes.js': 'modes.js', '/activities.js': 'activities.js', '/style.css': 'style.css'}[route]
                    mime = 'text/javascript; charset=utf-8' if route.endswith('.js') else ('text/css; charset=utf-8' if route.endswith('.css') else 'text/html; charset=utf-8')
                    self.send_data(200, (Path(__file__).parent / 'static' / name).read_bytes(), mime)
                else:
                    self.send_data(404, {'error': 'Not found'})
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logging.exception('Library read failed')
                self.send_data(400, {'error': str(exc)})

        def do_POST(self):
            upload_slot = None
            try:
                origin = self.headers.get('Origin')
                expected_origin = 'http://' + self.headers.get('Host', '')
                if not self.allowed_host() or self.headers.get('X-DJTable-CSRF') != token or (origin and origin != expected_origin):
                    self.send_data(403, {'error': 'Reload this page on the Pi local address before saving'})
                    return
                url = urlsplit(self.path)
                mode = modes.validate(parse_qs(url.query).get('mode', [modes.selected()])[0]) if modes else 'teenage_disco'
                library = modes.library(mode) if modes else default_library
                size = int(self.headers.get('Content-Length', '0'))
                limit = MAX_UPLOAD if url.path == '/api/upload' else 16384
                if self.headers.get('Transfer-Encoding') or not 0 < size <= limit:
                    self.send_data(413, {'error': 'Request is missing a length or is too large'})
                    self.close_connection = True
                    return
                if url.path == '/api/upload':
                    gate = getattr(self.server, 'uploads', None)
                    if gate is not None:
                        if not gate.acquire(blocking=False):
                            self.send_data(503, {'error': 'Two uploads are already running. Please retry shortly.'})
                            self.close_connection = True
                            return
                        upload_slot = gate
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError('Upload was interrupted')
                if url.path == '/api/upload':
                    query = parse_qs(url.query)
                    slot = query.get('slot', ['song'])[0]
                    if modes and slot.startswith(('colours/', 'symbols/')):
                        library = modes.library('teenage_disco')
                    state = library.upload(raw, query.get('title', [''])[0], slot)
                elif url.path == '/api/mode' and modes:
                    value = json.loads(raw)
                    modes.select(value.get('mode'))
                    state = {'selected': modes.selected()}
                elif url.path == '/api/activity':
                    value = json.loads(raw)
                    activities.select(value.get('activity'))
                    state = {'selected': activities.selected()}
                elif url.path == '/api/maker':
                    value = json.loads(raw)
                    state = activities.maker_request(value.get('action'), value.get('quantize'))
                elif url.path == '/api/controls':
                    value = json.loads(raw)
                    if not isinstance(value, dict): raise ValueError('Expected a slider selection')
                    state = controls.select(value.get('name'), value.get('position'))
                elif url.path == '/api/wifi':
                    from .wifi import request
                    value = json.loads(raw)
                    state = request({'action': 'connect', 'ssid': value.get('ssid'), 'password': value.get('password')})
                elif url.path == '/api/change':
                    value = json.loads(raw)
                    if modes and value.get('action') == 'reset' and str(value.get('value', '')).startswith(('colours/', 'symbols/')):
                        library = modes.library('teenage_disco')
                    state = library.change(value.get('action'), value.get('value'))
                else:
                    self.send_data(404, {'error': 'Not found'})
                    return
                self.send_data(200, state)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.send_data(400, {'error': str(exc)})
            finally:
                if upload_slot is not None: upload_slot.release()

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(Path(__file__).resolve().parents[1] / 'config.json'))
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    config = read_config(args.config)
    library = Library(config['library_dir'], config['sample_rate'])
    from .modes import Modes
    with SampleServer((args.host, args.port), handler_for(library, config['sample_root'], Modes(config))) as server:
        logging.info('Sample manager listening on %s:%s', args.host, args.port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
