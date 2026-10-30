attribute vec3 aPrevious;
attribute float aType;
attribute float aRegime;
attribute float aSeed;
uniform float uBlend;
uniform float uPixelRatio;
uniform float uTime;
uniform float uMotion;
uniform vec3 uLayers;
uniform float uRegime;
varying vec3 vColor;
varying float vAlpha;
void main() {
  vec3 p = mix(aPrevious, position, uBlend);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  bool debris = aType > 0.5 && aType < 1.5;
  float visibleLayer = aType < 0.5 ? uLayers.x : (debris ? uLayers.y : uLayers.z);
  if (uRegime > 0.5 && abs(aRegime - uRegime) > 0.1) visibleLayer = 0.0;
  vColor = aType < 0.5 ? vec3(1.0, 0.15, 0.22) : (debris ? vec3(1.0, 0.45, 0.12) : vec3(0.72, 0.78, 0.87));
  float flicker = debris ? (0.75 + sin(uTime * 0.8 * uMotion + aSeed * 0.78) * 0.16) : 1.0;
  // Selection adds a ring; the complete enabled catalog keeps the same visibility.
  vAlpha = visibleLayer * flicker * 0.88;
  gl_PointSize = (debris ? 2.1 : (aType > 1.5 ? 2.6 : 2.4)) * uPixelRatio;
  gl_Position = projectionMatrix * mv;
}
