import { describe, expect, it } from 'vitest';
import type { CatalogObject } from '../api/types';
import { modelVariant } from './SelectedModel';

const object = (name: string, type: CatalogObject['type'], noradId = 100): CatalogObject => ({
  name, type, noradId, active: true, maneuverable: type === 'PAYLOAD', omm: {},
});

describe('selected-object figure', () => {
  it('chooses recognizable variants without adding API fields', () => {
    expect(modelVariant(object('ISS (ZARYA)', 'PAYLOAD', 25544))).toBe('iss');
    expect(modelVariant(object('STARLINK-31502', 'PAYLOAD'))).toBe('starlink');
    expect(modelVariant(object('CUBESAT-1', 'PAYLOAD'))).toBe('cubesat');
    expect(modelVariant(object('Weather satellite', 'PAYLOAD'))).toBe('satellite');
    expect(modelVariant(object('SL-16 R/B', 'ROCKET_BODY'))).toBe('rocket');
    expect(modelVariant(object('COSMOS 1408 DEB', 'DEBRIS'))).toBe('debris');
  });
});
