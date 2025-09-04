{
  "name": "sift",
  "description": "MongoDB query filtering in JavaScript",
  "version": "17.1.3",
  "repository": "crcn/sift.js",
  "sideEffects": false,
  "author": {
    "name": "Craig Condon",
    "email": "craig.j.condon@gmail.com"
  },
  "license": "MIT",
  "engines": {},
  "typings": "./index.d.ts",
  "husky": {
    "hooks": {
      "pre-commit": "pretty-quick --staged"
    }
  },
  "devDependencies": {
    "@rollup/plugin-replace": "^2.3.2",
    "@rollup/plugin-typescript": "8.2.1",
    "@types/node": "^13.7.0",
    "bson": "^6.6.0",
    "eval": "^0.1.8",
    "husky": "^9.0.11",
    "mocha": "10.4.0",
    "mongodb": "^3.6.6",
    "prettier": "3.2.5",
    "pretty-quick": "^4.0.0",
    "rimraf": "^5.0.5",
    "rollup": "^4.14.2",
    "@rollup/plugin-terser": "^0.4.4",
    "tslib": "2.6.2",
    "typescript": "5.4.5"
  },
  "main": "./index.js",
  "module": "./es5m/index.js",
  "es2015": "./es/index.js",
  "scripts": {
    "clean": "rimraf lib es5m es",
    "prebuild": "npm run clean && npm run build:types",
    "build": "rollup -c",
    "build:types": "tsc -p tsconfig.json --emitDeclarationOnly --outDir lib",
    "test": "npm run test:spec && npm run test:types",
    "test:spec": "mocha ./test -R spec",
    "test:types": "cd test && tsc types.ts --noEmit",
    "prepublishOnly": "npm run build && npm run test"
  },
  "files": [
    "es",
    "es5m",
    "lib",
    "src",
    "*.d.ts",
    "*.js.map",
    "index.js",
    "sift.csp.min.js",
    "sift.min.js",
    "MIT-LICENSE.txt"
  ]
}
