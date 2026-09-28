# Frontend source baseline

Source: https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web

Commit: `3d57a9a0125a0ca13e5d096f7092e4e494ed389e` (v1.2.1).
Corresponding original build: `06a659b114fff788cf0daaa86e484576db4975bf`.

Downloaded from the official commit archive on 2026-09-22. Original licenses are
preserved. This directory contains maintainable source with local 心迹 changes;
the `frontend` submodule remains the original build for fallback. Build web with
`npm ci --ignore-scripts` then `npm run build:web`. No Electron install is needed.

Local changes: bounded procedural nod and gaze, Actions transport, interruption
cleanup. The nod uses ParamAngleY; gaze uses ParamEyeBallX/Y only when the actual
model contains these parameters. Unsupported controls leave the model unchanged.
