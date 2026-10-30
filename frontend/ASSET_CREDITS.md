# Asset credits

All scene textures and fonts are served locally. The application makes no runtime requests to these source repositories.

## Earth imagery

- **Daytime Earth / Blue Marble:** NASA imagery, obtained through [turban/webgl-earth, 2_no_clouds_4k.jpg](https://raw.githubusercontent.com/turban/webgl-earth/master/images/2_no_clouds_4k.jpg). Bundled as `public/textures/earth-day.jpg` and the locally encoded, 4096-pixel-wide `earth-day.webp`. The upstream Earth experiment provides the equirectangular source used for the globe.
- **Earth at night:** source from [vasturiano/three-globe, earth-night.jpg](https://raw.githubusercontent.com/vasturiano/three-globe/master/example/img/earth-night.jpg), bundled as `earth-night.jpg` and locally encoded at 2048 pixels wide as `earth-night.webp`. The texture is used for an illustrative warm city-light layer.
- **Clouds:** source from [turban/webgl-earth, fair_clouds_4k.png](https://raw.githubusercontent.com/turban/webgl-earth/master/images/fair_clouds_4k.png), bundled as `earth-clouds.png` and locally encoded at 2048 pixels wide as `earth-clouds.webp`.
- **Water mask:** source from [vasturiano/three-globe, earth-water.png](https://raw.githubusercontent.com/vasturiano/three-globe/master/example/img/earth-water.png), bundled as `earth-water.png`.

Source textures were resized and encoded to WebP locally with Pillow. The renderer uses the WebP cloud layer and the dedicated `earth-water.png` mask for surface specular response.

NASA imagery is credited to NASA. Do not imply NASA endorsement of OrbitSentinel. Repository source links record where the bundled copies came from; they do not assert that every third-party example asset shares the repository's software license.

## Typefaces

Fonts are bundled from Fontsource packages. Each package includes its original license file in `node_modules/@fontsource/<family>/LICENSE` after installation. Copies are shipped with the source and static deployment in `public/licenses/Archivo-OFL.txt`, `public/licenses/IBM-Plex-Sans-OFL.txt` and `public/licenses/IBM-Plex-Mono-OFL.txt`.

| Typeface | Authors / copyright | License and upstream |
| --- | --- | --- |
| Archivo | The Archivo Project Authors / Omnibus-Type | [SIL Open Font License 1.1](https://github.com/Omnibus-Type/Archivo/blob/master/OFL.txt) |
| IBM Plex Sans | IBM Corp. | [SIL Open Font License 1.1](https://github.com/IBM/plex/blob/master/LICENSE.txt) |
| IBM Plex Mono | IBM Corp. | [SIL Open Font License 1.1](https://github.com/IBM/plex/blob/master/LICENSE.txt) |

Fontsource distribution packages: [Archivo](https://fontsource.org/fonts/archivo), [IBM Plex Sans](https://fontsource.org/fonts/ibm-plex-sans), [IBM Plex Mono](https://fontsource.org/fonts/ibm-plex-mono).

## Original assets and generated data

The wordmark, UI SVG icon set, starfield, GLSL rendering effects and procedural satellite are authored for this project. No generated raster illustration or stock product mockup is used. The synthetic catalog and narrative event fixtures are authored demonstration data, not a redistributed CelesTrak snapshot.
