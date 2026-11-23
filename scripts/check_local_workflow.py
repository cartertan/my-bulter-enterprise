"""Run an opt-in, isolated local-model section workflow through the application API.

Inputs: Explicit --run-local consent and two downloaded Ollama model IDs.
Outputs: Sanitized check summary; isolated database retained in a temporary directory.
Assumptions: Local Ollama is available; no paid providers or real user notes are used.
This synthetic scale check does not establish researched content or final acceptance.
Author: Carter Tan.
"""
import argparse
import json
import logging
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from src.app import create_app, parse_presentation_outline

LOGGER = logging.getLogger(__name__)
SCOPES = ["Request and purpose", "Attribute selection", "Explicit approval",
          "Sharing and minimization", "Refusal and recovery", "Audit and limitations"]


def mission_payload(bots: list[str]) -> dict:
    """Use explicit identity-disclosure semantics rather than an ambiguous wallet brief."""
    return {
        'prompt': 'Create an explicitly fictional digital identity wallet workflow. A holder selects identity attributes (for example an age-over-18 assertion) for a requesting verifier. Consent means the holder approves those specific attributes for that verifier and purpose before disclosure. Refusal sends no attributes. This is not a payment wallet, financial transfer, login tutorial, or approval to distribute this presentation. Each section needs three substantive slides with speaker notes explaining operation, failure handling and limitations. Keep bodies concise and complete. Do not claim real deployments or research. Follow the native outline schema.',
        'bulter_ids': list(bots), 'sections': list(SCOPES), 'section_slide_counts': [3] * 6,
        'duration_budget_seconds': 1800, 'expected_slide_count': 18,
        'exact_duration_seconds': 1800, 'slide_duration_seconds': 100,
        'review_criteria': [
            'The section is explicitly fictional and explains its assigned identity-attribute disclosure scope, not payment transfers or a login tutorial.',
            'Any approval or refusal described concerns the holder disclosing selected identity attributes to a verifier for a stated purpose, not permission to distribute the presentation.',
            'Every slide body contains complete sentences or complete concise bullet points, with no cut-off word or unfinished clause.',
            'Claims must be consistent between bodies and speaker notes: distinguish initial attribute disclosure from later verifier use, and refusal signals from identity attributes.',
            'Native flow evidence: Flow labels must match the body and notes in actor and order: the verifier requests attributes for a purpose; the holder reviews that purpose before approval; disclosure follows approval.']}


def inspect_mission(mission: dict) -> dict:
    """Independently count retained outlines; never convert model PASS into acceptance."""
    slides, seconds, invalid = 0, 0, 0
    for step in mission.get('steps', [])[::2]:
        try:
            outline = parse_presentation_outline(step['output'])
        except (KeyError, ValueError):
            invalid += 1
            continue
        if (len(outline.slides) != 3 or outline.discussion_seconds != 0
                or any(slide.duration_seconds != 100 for slide in outline.slides)):
            invalid += 1
        slides += len(outline.slides)
        seconds += sum(slide.duration_seconds for slide in outline.slides) + outline.discussion_seconds
    complete = (mission.get('status') == 'completed' and len(mission.get('steps', [])) == 12
                and invalid == 0 and slides == 18 and seconds == 1800)
    return {'status': mission.get('status'), 'steps': len(mission.get('steps', [])),
            'slides': slides, 'declared_seconds': seconds, 'invalid_outlines': invalid,
            'scale_checks_pass': complete, 'user_acceptance': mission.get('acceptance_status'),
            'content_quality': 'not_assessed', 'rendered_quality': 'not_assessed'}


def main() -> int:
    """Run twelve bounded local calls only after explicit command-line opt-in."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-local', action='store_true')
    parser.add_argument('--author-model', default='qwen3.8:27b')
    parser.add_argument('--reviewer-model', default='granite4.1:30b')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    LOGGER.setLevel(logging.INFO)
    if not args.run_local:
        parser.error('--run-local is required; this test makes up to twelve local model calls')
    root = Path(tempfile.mkdtemp(prefix='bulter-scale-review-'))
    try:
        app = create_app(root / 'isolated.sqlite3')
        with TestClient(app) as client:
            client.headers['x-bulter-token'] = app.state.csrf
            bots = []
            for name, model in [('Author', args.author_model), ('Reviewer', args.reviewer_model)]:
                response = client.post('/api/bulters', json={'name': name, 'role': name,
                    'provider': 'ollama', 'model': model, 'thinking': 'off', 'output_tokens': 4096})
                response.raise_for_status()
                bots.append(response.json()['id'])
            response = client.post('/api/missions', json=mission_payload(bots))
            response.raise_for_status()
            deadline = time.monotonic() + 660
            while True:
                mission = client.get('/api/state').json()['missions'][0]
                if mission['status'] not in {'queued', 'running'}:
                    break
                if time.monotonic() >= deadline:
                    LOGGER.error('Bounded observation deadline reached; no acceptance claimed.')
                    return 1
                time.sleep(1)
            summary = inspect_mission(mission)
            LOGGER.info('%s', json.dumps(summary, sort_keys=True))
            LOGGER.info('Isolated records retained at %s; do not publish runtime records.', root)
            return 0 if summary['scale_checks_pass'] else 1
    except Exception as exc:
        # Response bodies may contain generated content; log only the failure type.
        LOGGER.error('Local workflow check failed (%s); no acceptance claimed.', type(exc).__name__)
        return 1


if __name__ == '__main__':
    sys.exit(main())
