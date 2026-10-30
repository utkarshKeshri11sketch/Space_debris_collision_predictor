uniform sampler2D uDay;
uniform sampler2D uNight;
uniform sampler2D uWater;
uniform sampler2D uClouds;
uniform vec3 uSun;
varying vec2 vUv;
varying vec3 vNormal;
varying vec3 vWorld;
void main() {
  vec3 normal = normalize(vNormal);
  float sunlight = dot(normal, normalize(uSun));
  // A finite-width terminator models sunlight scattered through the atmosphere.
  float day = smoothstep(-0.12, 0.16, sunlight);
  vec3 albedo = pow(texture2D(uDay, vUv).rgb, vec3(2.2));
  vec3 night = texture2D(uNight, vUv).rgb;
  vec3 warmLights = pow(night, vec3(1.65)) * vec3(1.1, 0.75, 0.39);
  vec3 viewDirection = normalize(cameraPosition - vWorld);
  float ocean = texture2D(uWater, vUv).r;
  float specular = pow(max(dot(reflect(-normalize(uSun), normal), viewDirection), 0.0), 72.0);
  vec3 lit = albedo * (0.20 + max(sunlight, 0.0) * 1.5);
  lit *= 1.0 - texture2D(uClouds, vUv + vec2(0.001, 0.0)).r * 0.075;
  lit += specular * ocean * vec3(0.15, 0.22, 0.28);
  vec3 dark = albedo * 0.022 + warmLights * 0.64;
  float grazing = pow(1.0 - max(dot(viewDirection, normal), 0.0), 3.3);
  vec3 color = mix(dark, lit, day);
  color += vec3(0.08, 0.28, 0.46) * grazing * smoothstep(-0.2, 0.55, sunlight) * 0.34;
  gl_FragColor = vec4(color, 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
