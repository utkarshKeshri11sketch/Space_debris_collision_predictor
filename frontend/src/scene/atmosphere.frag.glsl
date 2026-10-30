uniform vec3 uSun;
varying vec3 vNormal;
varying vec3 vWorld;
void main() {
  vec3 normal = normalize(vNormal);
  vec3 viewDirection = normalize(cameraPosition - vWorld);
  // Fresnel is confined to the grazing limb of the 1.021-radius shell.
  float fresnel = pow(1.0 - abs(dot(viewDirection, normal)), 5.5);
  float light = smoothstep(-0.30, 0.75, dot(normal, normalize(uSun)));
  float alpha = fresnel * (0.11 + light * 0.7);
  gl_FragColor = vec4(mix(vec3(0.05, 0.22, 0.50), vec3(0.30, 0.67, 0.94), light), alpha);
}
