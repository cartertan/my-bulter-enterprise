"""Local visual safety and routing tests using synthetic data.

Inputs: Graph fixtures and mocked Ollama discovery. Outputs: pytest assertions.
Assumptions: No real model downloads or inference. Author: Carter Tan.
"""

import asyncio
from unittest.mock import patch
import xml.etree.ElementTree as ET

import httpx
import pytest

from src.app import BulterInput
from src.local_visuals import render_graph, generate_picture
from src.providers import discover


def test_graph_escapes_active_content() -> None:
    """Model strings stay text, never scripts, links or embedded SVG elements."""
    label = '<script>alert(1)</script><image href="https://example.test"/>'
    output = render_graph({"nodes": [{"id": "a", "label": label}], "edges": []})
    root = ET.fromstring(output)
    assert not any(n.tag.endswith(('script', 'image', 'a')) for n in root.iter())
    assert b'&lt;script&gt;' in output


@pytest.mark.parametrize('graph', [
    {"nodes": [], "edges": []},
    {"nodes": [None], "edges": []},
    {"nodes": [{"id": "a", "label": "a"}] * 2, "edges": []},
    {"nodes": [{"id": "a", "label": "a"}], "edges": [{"source": "a", "target": "b", "label": "x"}]},
    {"nodes": [{"id": "a", "label": "a", "onclick": "bad"}], "edges": []},
])
def test_graph_rejects_invalid_data(graph: dict) -> None:
    """Reject malformed graphs before creating output."""
    with pytest.raises(ValueError):
        render_graph(graph)


def test_image_model_cannot_be_chat_bulter() -> None:
    """Custom IDs cannot bypass the image/chat boundary."""
    for model in ('x/flux2-klein:4b', 'x/z-image-turbo:fp8'):
        with pytest.raises(ValueError, match='Image models'):
            BulterInput(name='Test', role='Test', provider='ollama', model=model)


def test_discovery_separates_image_and_embedding_models() -> None:
    """Dashboard inventory sees all installed models but chat sees chat models only."""
    names = ['qwen3.8:27b', 'x/flux2-klein:4b', 'x/z-image-turbo:fp8', 'qwen3-embedding:4b']
    response = httpx.Response(200, request=httpx.Request('GET', 'http://localhost'), json={'models': [{'name': n} for n in names]})
    async def fake_get(*args, **kwargs):
        return response
    with patch('httpx.AsyncClient.get', fake_get):
        result = asyncio.run(discover('ollama'))
    assert result['models'] == ['qwen3.8:27b']
    assert result['installed_models'] == names
    assert result['image_models'] == names[1:3]


def test_picture_worker_is_offline_and_prompt_not_in_argv(tmp_path) -> None:
    """Shell syntax stays stdin data; credentials and cloud fallback are excluded."""
    import json
    prompt = 'a picture; $(touch unsafe)'
    def fake_run(command, **kwargs):
        assert prompt not in command
        assert json.loads(kwargs['input'])['prompt'] == prompt
        assert not kwargs.get('shell')
        assert kwargs['env']['HF_HUB_OFFLINE'] == '1'
        assert kwargs['env']['HF_HUB_DISABLE_TELEMETRY'] == '1'
        assert 'OPENAI_API_KEY' not in kwargs['env']
        (tmp_path / 'image.png').write_bytes(b'fixture')
        return type('Result', (), {'returncode': 0})()
    with patch('pathlib.Path.is_file', return_value=True), patch('subprocess.run', side_effect=fake_run):
        generate_picture('flux', prompt, tmp_path)


def test_missing_engine_fails_before_subprocess(tmp_path) -> None:
    """No implicit installation occurs while a user is generating a picture."""
    with patch('pathlib.Path.is_file', return_value=False), patch('subprocess.run') as run:
        with pytest.raises(ValueError, match='setup script'):
            generate_picture('flux', 'synthetic', tmp_path)
        run.assert_not_called()


def test_image_status_requires_complete_verified_files(tmp_path) -> None:
    """A receipt is insufficient if its model files are missing or truncated."""
    import json
    from src.image_engine import engine_status, MODELS, ENGINE_VERSION
    engine = tmp_path / 'mflux-venv/bin/python'
    engine.parent.mkdir(parents=True)
    engine.write_bytes(b'fake')
    model = tmp_path / 'image-models/flux-4bit'
    model.mkdir(parents=True)
    (model / 'verified.json').write_text(json.dumps({'engine': ENGINE_VERSION, 'revision': MODELS['flux']['revision'], 'files': {'weights.safetensors': 5}}))
    assert 'Ready' not in engine_status(tmp_path)['models']['flux']['status']
    (model / 'weights.safetensors').write_bytes(b'12345')
    assert 'Ready' in engine_status(tmp_path)['models']['flux']['status']
    (model / 'weights.safetensors').write_bytes(b'123')
    assert 'Ready' not in engine_status(tmp_path)['models']['flux']['status']
