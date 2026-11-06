import json
import pytest
from quix_knowledge.openrouter import OpenRouterDecision, load_settings


def test_settings_and_typed_provider_without_exposing_key(tmp_path):
    env = tmp_path / '.env'
    env.write_text('OPENROUTER_API_KEY="secret"\nOPENROUTER_DEC_MODEL_2=liquid/d1.1\n')
    settings = load_settings(env, 2)
    captured = {}
    def transport(request, timeout):
        captured['body'] = json.loads(request.data)
        return {'model':'liquid/d1.1-pinned', 'provider':'Liquid', 'answers':{'judgment':{'type':'noul','noul':0.8}}, 'usage':{'cost':0.00001}}
    provider = OpenRouterDecision(settings, transport=transport)
    response = provider({'text':'retry'}, 'relevant')
    assert response['probability'] == 0.8
    assert response['outcome'] == 'unclear'
    assert response['model'] == 'liquid/d1.1-pinned'
    assert response['usage']['cost'] == 0.00001
    assert captured['body']['questions']['judgment']['type'] == 'noul'
    assert 'secret' not in repr(settings)

def test_rejects_invalid_response_and_missing_settings(tmp_path):
    with pytest.raises(ValueError):
        load_settings(tmp_path/'missing', 2)
    from quix_knowledge.openrouter import Settings
    provider = OpenRouterDecision(Settings('key','m'), transport=lambda *args: {'answers':{'judgment':{'type':'noul','noul':2}}})
    with pytest.raises(ValueError):
        provider({},'relevant')

def test_explicit_thresholds_are_opt_in():
    from quix_knowledge.openrouter import Settings
    transport = lambda *args: {'answers':{'judgment':{'type':'noul','noul':0.9}}}
    provider = OpenRouterDecision(Settings('key','m'), transport=transport, thresholds=(0.2,0.8))
    assert provider({},'relevant')['outcome'] == 'supported'
    with pytest.raises(ValueError):
        OpenRouterDecision(Settings('key','m'), thresholds=(0.9,0.1))
