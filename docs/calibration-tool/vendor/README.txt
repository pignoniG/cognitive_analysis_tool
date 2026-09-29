# Vendored three.js

`three-slim.module.js` is three.js r186 (0.186.1, MIT, see `three.LICENSE`) reduced to the seven classes the VR
calibration uses, so the page runs without a network connection. Rebuild it with:

```sh
echo "export { WebGLRenderer, Scene, PerspectiveCamera, Mesh, SphereGeometry, MeshBasicMaterial, BackSide, SRGBColorSpace, NoToneMapping, REVISION } from 'three';" > entry.js
npm i three@0.186.1 esbuild
npx esbuild entry.js --bundle --minify --format=esm --outfile=three-slim.module.js
```
