attribute float aPhase;
attribute float aKick;
attribute float aNode;
uniform float uYear;
uniform float uRadius;
uniform float uInclination;
uniform float uNode;
uniform float uPhase;
uniform float uPixelRatio;
varying float vAge;
void main() {
  // A seeded velocity kick changes period; J2 differential nodal drift slowly fans the ring out.
  // This is a visual analytic approximation, not a long-term collision propagator.
  float smear = min(uYear * 10.0, 1.0);
  float phase = uPhase + aPhase * smear + aKick * uYear * 6.0;
  float node = uNode + aNode * uYear * 0.13;
  float inclination = uInclination + aKick * min(uYear, 8.0) * 0.08;
  float radius = uRadius + aKick * min(uYear, 3.0) * 0.065;
  vec3 p = vec3(cos(phase), sin(phase) * sin(inclination), -sin(phase) * cos(inclination)) * radius;
  p.xz = mat2(cos(node), -sin(node), sin(node), cos(node)) * p.xz;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = 2.5 * uPixelRatio;
  vAge = min(uYear * 3.0, 1.0);
}
