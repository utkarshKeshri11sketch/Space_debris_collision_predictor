varying float vAge;
void main() {
  float r = length(gl_PointCoord - 0.5) * 2.0;
  if (r > 1.0) discard;
  vec3 color = mix(vec3(1.0, 0.92, 0.71), vec3(1.0, 0.37, 0.10), vAge);
  gl_FragColor = vec4(color, exp(-r*r*5.0) * 0.86);
}
