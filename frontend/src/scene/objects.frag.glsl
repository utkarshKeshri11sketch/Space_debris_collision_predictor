varying vec3 vColor;
varying float vAlpha;
void main() {
  float radius = length(gl_PointCoord - 0.5) * 2.0;
  if (radius > 1.0 || vAlpha < 0.01) discard;
  float core = exp(-radius * radius * 4.0);
  float halo = (1.0 - radius) * 0.18;
  // Alpha-over compositing preserves class hue even where many LEO points overlap.
  gl_FragColor = vec4(vColor, min(1.0, core + halo) * vAlpha);
}
