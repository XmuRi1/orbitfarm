"""Shared catalogue and input validation for FastAPI and the legacy HTTP server."""
from pathlib import Path

from scoring import read_json

CROPS = read_json(Path(__file__).resolve().parent / 'data' / 'crops.json')


def _validate_assess_body(body: dict) -> None:
    farm = body.get('farm')
    if not isinstance(farm, dict):
        raise ValueError('farm must be a JSON object')
    if not isinstance(farm.get('farm_id'), str) or not farm['farm_id'].strip():
        raise ValueError('farm.farm_id must be a nonempty string')
    if not isinstance(farm.get('location'), dict):
        raise ValueError('farm.location must be a JSON object')
    observations = farm.get('observations')
    if not isinstance(observations, list):
        raise ValueError('farm.observations must be an array')
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise ValueError(f'farm.observations[{index}] must be a JSON object')
        if not isinstance(observation.get('parameter_id'), str):
            raise ValueError(f'farm.observations[{index}].parameter_id must be a string')
        for field in ('context', 'source'):
            if field in observation and observation[field] is not None and not isinstance(observation[field], dict):
                raise ValueError(f'farm.observations[{index}].{field} must be a JSON object')
