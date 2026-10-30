import { Bloom, EffectComposer } from '@react-three/postprocessing';

/** Only deliberately HDR signals pass this threshold; Earth and catalog stay crisp. */
export default function BloomEffects() {
  return (
    <EffectComposer multisampling={0} enableNormalPass={false}>
      <Bloom luminanceThreshold={1.15} luminanceSmoothing={0.2} intensity={0.65} mipmapBlur radius={0.65} />
    </EffectComposer>
  );
}
