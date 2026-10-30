import { Bloom, EffectComposer, ToneMapping, Vignette } from '@react-three/postprocessing';
import { ToneMappingMode } from 'postprocessing';

/** HDR sources bloom before ACES; composer disables the renderer's own tone mapping.
 * ToneMappingEffect reads renderer.toneMappingExposure, preserving the existing 1.18.
 */
export default function BloomEffects() {
  return (
    <EffectComposer multisampling={0} enableNormalPass={false}>
      <Bloom luminanceThreshold={1.15} luminanceSmoothing={0.2} intensity={0.55} mipmapBlur radius={0.65} resolutionScale={0.5} />
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      <Vignette eskil={false} offset={0.3} darkness={0.12} />
    </EffectComposer>
  );
}
