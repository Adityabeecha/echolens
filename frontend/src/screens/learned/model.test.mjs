import test from 'node:test';
import assert from 'node:assert/strict';
import { approvalExample, patternProblemIds, learnedSection } from './model.ts';
test('accuracy example uses actual reviewed counts and rates', () => {
  assert.deepEqual(approvalExample(7, 4 / 7), { reviewed: 7, approved: 4 });
  assert.equal(approvalExample(0, null), null);
  assert.equal(approvalExample(7, null), null);
});
test('another product’s problem numbers never become local links', () => {
  assert.deepEqual(patternProblemIds({ cross_product: true, cases: [11, 12] }), []);
  assert.deepEqual(patternProblemIds({ cases: [11, 12] }), [11, 12]);
});
test('section URLs preserve legacy entry points', () => {
  assert.equal(learnedSection('?section=rules', 'map'), 'rules');
  assert.equal(learnedSection('#/p/3/intelligence', 'map'), 'fixes');
  assert.equal(learnedSection('#/p/3/patterns', 'fixes'), 'fixes');
  assert.equal(learnedSection('#/p/3/intelligence?section=unknown', 'map'), 'fixes');
});
