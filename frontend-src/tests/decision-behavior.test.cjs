const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(relative) {
  const source = fs.readFileSync(path.join(__dirname, '../src/renderer/src/utils', relative), 'utf8');
  const result = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } });
  const module = { exports: {} };
  new Function('module', 'exports', 'require', result.outputText)(module, module.exports, require);
  return module.exports;
}

test('one bounded nod has zero offsets at both ends', () => {
  const { DecisionBehavior } = load('decision-behavior.ts');
  const behavior = new DecisionBehavior();
  behavior.start('gentle_nod', 'attentive', 100);
  assert.equal(behavior.sample(100).angleY, 0);
  assert.equal(behavior.sample(700).angleY, -8);
  assert.equal(behavior.sample(1300).angleY, 0);
  assert.equal(behavior.sample(5000).angleY, 0);
});

test('gaze is bounded, unknown controls do nothing, clear restores baseline', () => {
  const { DecisionBehavior } = load('decision-behavior.ts');
  const behavior = new DecisionBehavior();
  behavior.start('gentle_nod', 'soft', 0);
  assert.equal(behavior.sample(600).eyeY, -0.15);
  behavior.clear();
  assert.deepEqual(behavior.sample(600), { angleY: 0, eyeX: null, eyeY: null });
  behavior.start('unknown', 'unknown', 0);
  assert.deepEqual(behavior.sample(600), { angleY: 0, eyeX: null, eyeY: null });
});

test('interrupt resolves pending audio and clears model controls exactly once', () => {
  const { audioManager } = load('audio-manager.ts');
  let clears = 0;
  let cancelled = 0;
  audioManager.setCurrentAudio({ pause() {}, load() {}, src: 'test' }, {
    decisionBehavior: { clear() { clears++; } },
  }, () => { cancelled++; });
  audioManager.stopCurrentAudioAndLipSync();
  audioManager.stopCurrentAudioAndLipSync();
  assert.equal(clears, 1);
  assert.equal(cancelled, 1);
  assert.equal(audioManager.hasCurrentAudio(), false);
});

test('natural finish clears gaze and stale cleanup cannot clear a newer audio', () => {
  const { audioManager } = load('audio-manager.ts');
  const oldAudio = {};
  const currentAudio = {};
  let clears = 0;
  audioManager.setCurrentAudio(oldAudio, {});
  audioManager.setCurrentAudio(currentAudio, { decisionBehavior: { clear() { clears++; } } });
  assert.equal(audioManager.isCurrentAudio(oldAudio), false);
  assert.equal(audioManager.isCurrentAudio(currentAudio), true);
  audioManager.clearCurrentAudio(oldAudio);
  assert.equal(clears, 0);
  assert.equal(audioManager.isCurrentAudio(currentAudio), true);
  audioManager.clearCurrentAudio(currentAudio);
  audioManager.clearCurrentAudio(currentAudio);
  assert.equal(clears, 1);
  assert.equal(audioManager.hasCurrentAudio(), false);
});

test('interruption detaches old audio before synchronous load events', () => {
  const { audioManager } = load('audio-manager.ts');
  let clears = 0;
  let cancelled = 0;
  const audio = {
    pause() {}, src: 'test',
    load() {
      assert.equal(audioManager.isCurrentAudio(audio), false);
      audioManager.clearCurrentAudio(audio);
    },
  };
  audioManager.setCurrentAudio(audio, { decisionBehavior: { clear() { clears++; } } }, () => { cancelled++; });
  audioManager.stopCurrentAudioAndLipSync();
  assert.equal(clears, 1);
  assert.equal(cancelled, 1);
});
