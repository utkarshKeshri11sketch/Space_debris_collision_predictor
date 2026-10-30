varying vec3 vColor;
varying float vAlpha;
void main() {
  float radius = length(gl_PointCoord - 0.5) * 2.0;
  if (radius > 1.0 || vAlpha < 0.01) discard;
  float core = exp(-radius * radius * 4.0);
  float halo = (1.0 - radius) * 0.18;
  // HDR at the small core crosses bloom's high threshold. A dim soft halo
  // stays in this same sprite/draw call; alpha-over preserves dense class hues.
  vec3 radiance = vColor * (1.0 + 4.2 * core) + vColor * halo;
  gl_FragColor = vec4(radiance, min(1.0, core + halo) * vAlpha);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
