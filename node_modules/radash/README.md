# Radash

:loud_sound: `/raw-dash/`

<div align="center">
  <p align="center">
    <img src="https://github.com/rayepps/radash/raw/master/banner.png" alt="radash" width="100%" style="border-radius:4px" />
  </p>
</div>

<div>
  <h3 align="center">
    Functional utility library - modern, simple, typed, powerful
  </h3>
</div>

<p align="center">
  <a href="https://bundlephobia.com/package/radash">
    <img src="https://img.shields.io/bundlephobia/minzip/radash?label=minzipped" alt="bundle size" height="18">
  </a>
  <a href="https://www.npmjs.com/package/radash">
    <img src="https://img.shields.io/npm/dm/radash.svg" alt="npm downloads" height="18">
  </a>
  <a href="https://www.npmjs.com/package/radash">
    <img src="https://img.shields.io/npm/v/radash.svg" alt="npm version" height="18">
  </a>
  <a href="https://github.com/rayepps/radash">
    <img src="https://img.shields.io/npm/l/radash.svg" alt="MIT license" height="18">
  </a>
</p>

<div align="center">
  <a href="https://radash-docs.vercel.app" target="_blank">
      Full Documentation
  </a>
</div>

## Install

```
yarn add radash
```

## Usage

A very brief kitchen sink. See the full documentation [here](https://radash-docs.vercel.app).

```ts
import * as _ from 'radash'

const gods = [{
  name: 'Ra',
  power: 'sun',
  rank: 100,
  culture: 'egypt'
}, {
  name: 'Loki',
  power: 'tricks',
  rank: 72,
  culture: 'norse'
}, {
  name: 'Zeus',
  power: 'lightning',
  rank: 96,
  culture: 'greek'
}]

_.max(gods, g => g.rank) // => ra
_.sum(gods, g => g.rank) // => 268
_.fork(gods, g => g.culture === 'norse') // => [[loki], [ra, zeus]]
_.sort(gods, g => g.rank) // => [ra, zeus, loki]
_.boil(gods, (a, b) => a.rank > b.rank ? a : b) // => ra

_.objectify(
  gods, 
  g => g.name.toLowerCase(), 
  g => _.pick(g, ['power', 'rank', 'culture'])
) // => { ra, zeus, loki }

const godName = _.get(gods, g => g[0].name)

const [err, god] = await _.try(api.gods.findByName)(godName)

const allGods = await _.map(gods, async ({ name }) => {
  return api.gods.findByName(name)
})
```

## Contributing

Contributions are welcome and appreciated! Check out the [contributing guide](./.github/contributing.md) before you dive in.
