import { json2satrec, type OMMJsonObject, type SatRec } from 'satellite.js';
/** Validate fields before native OMM initialization. Catalog IDs remain numbers: no TLE truncation. */
export function recordFromOmm(omm: Record<string, string | number>): SatRec {
  const number = (key: string, fallback?: number) => {
    const value = Number(omm[key] ?? fallback);
    if (!Number.isFinite(value)) throw new Error(`Invalid OMM ${key}`);
    return value;
  };
  const epoch = String(omm.EPOCH ?? '');
  if (!epoch || Number.isNaN(Date.parse(epoch.endsWith('Z') ? epoch : `${epoch}Z`))) throw new Error('Invalid OMM EPOCH');
  const noradId = number('NORAD_CAT_ID');
  const eccentricity = number('ECCENTRICITY');
  const meanMotion = number('MEAN_MOTION');
  const inclination = number('INCLINATION');
  if (!Number.isInteger(noradId) || noradId < 1 || noradId > 999999999) throw new Error('Invalid OMM NORAD_CAT_ID');
  if (eccentricity < 0 || eccentricity >= 1 || meanMotion <= 0 || inclination < 0 || inclination > 180) throw new Error('Invalid OMM orbital elements');
  const normalized: OMMJsonObject = {
    CCSDS_OMM_VERS: '3.0',
    OBJECT_NAME: String(omm.OBJECT_NAME ?? `NORAD ${noradId}`),
    OBJECT_ID: String(omm.OBJECT_ID ?? ''),
    EPOCH: epoch,
    MEAN_MOTION: meanMotion,
    ECCENTRICITY: eccentricity,
    INCLINATION: inclination,
    RA_OF_ASC_NODE: number('RA_OF_ASC_NODE'),
    ARG_OF_PERICENTER: number('ARG_OF_PERICENTER'),
    MEAN_ANOMALY: number('MEAN_ANOMALY'),
    EPHEMERIS_TYPE: 0,
    CLASSIFICATION_TYPE: omm.CLASSIFICATION_TYPE === 'C' ? 'C' : 'U',
    NORAD_CAT_ID: noradId,
    ELEMENT_SET_NO: number('ELEMENT_SET_NO', 1),
    REV_AT_EPOCH: number('REV_AT_EPOCH', 0),
    BSTAR: number('BSTAR', 0),
    MEAN_MOTION_DOT: number('MEAN_MOTION_DOT', 0),
    MEAN_MOTION_DDOT: number('MEAN_MOTION_DDOT', 0),
  };
  return json2satrec(normalized);
}
