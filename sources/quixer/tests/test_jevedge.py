import pytest
from quix_knowledge.jevedge import JevEdgeDecision


def test_local_decision_preserves_uncalibrated_score_and_stability():
    captured={}
    def transport(request,timeout):
        import json
        captured.update(json.loads(request.data))
        return {'probabilities':{'yes':0.8,'no':0.2},'choice':'yes','model':{'name':'edge0-35b','backend':'mlx'},'legal_mass':0.4,'stability':{'stable_across_permutations':True,'trials':2}}
    provider=JevEdgeDecision('http://127.0.0.1:8090',transport=transport,stability_trials=2)
    result=provider({'text':'retry'},'relevant')
    assert captured['stability_trials'] == 2
    assert result['outcome'] == 'unclear'
    assert result['probability'] == 0.8
    assert result['probability_status'] == 'conditional_option_score_uncalibrated'
    assert result['legal_mass'] == 0.4


def test_local_adapter_rejects_nonloopback_and_invalid_response():
    with pytest.raises(ValueError):
        JevEdgeDecision('https://example.com')
    with pytest.raises(ValueError):
        JevEdgeDecision('http://127.0.0.1:8090',transport=lambda *args:{'probabilities':{'yes':0.8,'no':0.8}})({},'relevant')
    with pytest.raises(ValueError):
        JevEdgeDecision('http://127.0.0.1:8090',transport=lambda *args:{'probabilities':{'yes':0.8,'no':0.2},'legal_mass':float('nan')})({},'relevant')


def test_unstable_permutations_do_not_act_on_thresholds():
    provider=JevEdgeDecision('http://localhost:8090',thresholds=(0.2,0.8),stability_trials=2,transport=lambda *args:{'probabilities':{'yes':0.9,'no':0.1},'stability':{'stable_across_permutations':False,'trials':2}})
    assert provider({},'relevant')['outcome'] == 'unclear'

def test_loopback_transport_sends_real_http_request():
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert self.path == '/v1/decisions'
            assert data['options'][0]['id'] == 'yes'
            body=json.dumps({'probabilities':{'yes':0.6,'no':0.4},'model':{'name':'fixture'}}).encode()
            self.send_response(200)
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self,*args):
            pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        result=JevEdgeDecision(f'http://127.0.0.1:{server.server_port}')({'text':'retry'},'relevant')
        assert result['probability'] == 0.6
        assert result['model'] == 'fixture'
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
