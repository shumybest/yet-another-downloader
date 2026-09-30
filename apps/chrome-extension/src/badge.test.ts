import assert from 'node:assert/strict';
import test from 'node:test';
import { formatBadgeCount } from './badge.ts';

test('hides the badge when a tab has no captures', () => {
  assert.equal(formatBadgeCount(0), '');
});

test('shows capture counts through 99', () => {
  assert.equal(formatBadgeCount(1), '1');
  assert.equal(formatBadgeCount(99), '99');
});

test('caps large capture counts at 99+', () => {
  assert.equal(formatBadgeCount(100), '99+');
  assert.equal(formatBadgeCount(999), '99+');
});

test('treats invalid and negative counts as empty', () => {
  assert.equal(formatBadgeCount(-1), '');
  assert.equal(formatBadgeCount(Number.NaN), '');
});
