<p align="center">
  <br />

  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/statelyai/public-assets/main/logos/xstate-logo-white-nobg.svg">
    <img alt="XState logotype" src="https://raw.githubusercontent.com/statelyai/public-assets/main/logos/xstate-logo-black-nobg.svg" width="200">
  </picture>
  <br />
    <strong>Actor-based state management & orchestration for complex app logic.</strong> <a href="https://stately.ai/docs">→ Documentation</a>
  <br />
  <br />
</p>

XState is a state management and orchestration solution for JavaScript and TypeScript apps. It has _zero_ dependencies, and is useful for frontend and backend application logic.

It uses event-driven programming, state machines, statecharts, and the actor model to handle complex logic in predictable, robust, and visual ways. XState provides a powerful and flexible way to manage application and workflow state by allowing developers to model logic as actors and state machines.

### ✨ Create state machines visually in Stately Studio → [state.new](https://state.new)

---

📖 [Read the documentation](https://stately.ai/docs)

➡️ [Create state machines with the Stately Editor](https://stately.ai/editor)

🖥 [Download our VS Code extension](https://marketplace.visualstudio.com/items?itemName=statelyai.stately-vscode)

📑 Inspired by the [SCXML specification](https://www.w3.org/TR/scxml/)

💬 Chat on the [Stately Discord Community](https://discord.gg/xstate)

✍️ Browse through the many [XState examples](https://github.com/statelyai/xstate/tree/main/examples)

## Templates

Get started by forking one of these templates on CodeSandbox:

<table>
<thead>
<tr><th>Template</th><th></th></tr>
</thead>
<tbody>

<tr>
<td>

[🤖 XState Template (CodeSandbox)](https://codesandbox.io/p/devbox/github/statelyai/xstate/tree/main/templates/vanilla-ts)

[![Open in StackBlitz](https://developer.stackblitz.com/img/open_in_stackblitz.svg)](https://stackblitz.com/github/statelyai/xstate/tree/main/templates/vanilla-ts?file=%2Fsrc%2FfeedbackMachine.ts)

</td>
<td>

- XState v5
- TypeScript
- _No framework_

</td>
</tr>

<tr>
<td>

[⚛️ XState + React Template (CodeSandbox)](https://codesandbox.io/p/devbox/github/statelyai/xstate/tree/main/templates/react-ts)

[![Open in StackBlitz](https://developer.stackblitz.com/img/open_in_stackblitz.svg)](https://stackblitz.com/github/statelyai/xstate/tree/main/templates/react-ts?file=%2Fsrc%2FfeedbackMachine.ts)

</td>
<td>

- [React](https://react.dev/)
- XState v5
- TypeScript

</td>
</tr>

<tr>
<td>

[💚 XState + Vue Template (CodeSandbox)](https://codesandbox.io/p/devbox/github/statelyai/xstate/tree/main/templates/vue-ts)

[![Open in StackBlitz](https://developer.stackblitz.com/img/open_in_stackblitz.svg)](https://stackblitz.com/github/statelyai/xstate/tree/main/templates/vue-ts?file=%2Fsrc%2FfeedbackMachine.ts)

</td>
<td>

- [Vue](https://vuejs.org/)
- XState v5
- TypeScript

</td>
</tr>

<tr>
<td>

[🧡 XState + Svelte Template (CodeSandbox)](https://codesandbox.io/p/devbox/github/statelyai/xstate/tree/main/templates/svelte-ts)

[![Open in StackBlitz](https://developer.stackblitz.com/img/open_in_stackblitz.svg)](https://stackblitz.com/github/statelyai/xstate/tree/main/templates/svelte-ts?file=%2Fsrc%2FfeedbackMachine.ts)

</td>
<td>

- [Svelte](https://svelte.dev/)
- XState v5
- TypeScript

</td>
</tr>

</tbody>
</table>

## Super quick start

```bash
npm install xstate
```

```ts
import { createMachine, createActor, assign } from 'xstate';

// State machine
const toggleMachine = createMachine({
  id: 'toggle',
  initial: 'inactive',
  context: {
    count: 0
  },
  states: {
    inactive: {
      on: {
        TOGGLE: { target: 'active' }
      }
    },
    active: {
      entry: assign({ count: ({ context }) => context.count + 1 }),
      on: {
        TOGGLE: { target: 'inactive' }
      }
    }
  }
});

// Actor (instance of the machine logic, like a store)
const toggleActor = createActor(toggleMachine);
toggleActor.subscribe((state) => console.log(state.value, state.context));
toggleActor.start();
// => logs 'inactive', { count: 0 }

toggleActor.send({ type: 'TOGGLE' });
// => logs 'active', { count: 1 }

toggleActor.send({ type: 'TOGGLE' });
// => logs 'inactive', { count: 1 }
```

## [Stately Studio](https://stately.ai)

- Visually create, edit, and collaborate on state machines
- Export to many formats, including XState v5
- Test path & documentation autogeneration
- Deploy to Stately Sky
- Generate & modify machines with Stately AI

<a href="stately.ai/registry/new?ref=github" title="Stately Studio">
  <img src="https://github.com/statelyai/xstate/assets/1093738/74ed9cbc-b824-4ed7-a16d-f104947af8a7" alt="XState Viz" width="800" />
</a>

**[state.new](https://stately.ai/registry/new?ref=github)**

## Why?

Statecharts are a formalism for modeling stateful, reactive systems. This is useful for declaratively describing the _behavior_ of your application, from the individual components to the overall application logic.

Read [📽 the slides](http://slides.com/davidkhourshid/finite-state-machines) ([🎥 video](https://www.youtube.com/watch?v=VU1NKX6Qkxc)) or check out these resources for learning about the importance of finite state machines and statecharts in user interfaces:

- [Statecharts - A Visual Formalism for Complex Systems](https://www.sciencedirect.com/science/article/pii/0167642387900359/pdf) by David Harel
- [The World of Statecharts](https://statecharts.github.io/) by Erik Mogensen

## Packages

| Package                                                                                       | Description                                                                  |
| --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| 🤖 `xstate`                                                                                   | Core finite state machine and statecharts library + interpreter              |
| [⚛️ `@xstate/react`](https://github.com/statelyai/xstate/tree/main/packages/xstate-react)     | React hooks and utilities for using XState in React applications             |
| [💚 `@xstate/vue`](https://github.com/statelyai/xstate/tree/main/packages/xstate-vue)         | Vue composition functions and utilities for using XState in Vue applications |
| [🎷 `@xstate/svelte`](https://github.com/statelyai/xstate/tree/main/packages/xstate-svelte)   | Svelte utilities for using XState in Svelte applications                     |
| [🥏 `@xstate/solid`](https://github.com/statelyai/xstate/tree/main/packages/xstate-solid)     | Solid hooks and utilities for using XState in Solid applications             |
| [🔍 `@xstate/inspect`](https://github.com/statelyai/xstate/tree/main/packages/xstate-inspect) | Inspection utilities for XState                                              |

## Finite State Machines

<table>
<thead><tr><th>Code</th><th>Statechart</th></tr></thead>
<tbody>
<tr>
<td>

```js
import { createMachine, createActor } from 'xstate';

const lightMachine = createMachine({
  id: 'light',
  initial: 'green',
  states: {
    green: {
      on: {
        TIMER: 'yellow'
      }
    },
    yellow: {
      on: {
        TIMER: 'red'
      }
    },
    red: {
      on: {
        TIMER: 'green'
      }
    }
  }
});

const actor = createActor(lightMachine);

actor.subscribe((state) => {
  console.log(state.value);
});

actor.start();
// logs 'green'

actor.send({ type: 'TIMER' });
// logs 'yellow'
```

<table>
<thead><tr><th>Code</th><th>Statechart</th></tr></thead>
<tbody>
<tr>
<td>

</td>
<td>

</td>
</tr>
</tbody>
</table>

</td>
<td>

<a href="https://stately.ai/registry/editor/fa443471-b416-4014-8e6f-12417863e4d4?mode=design&machineId=27e86036-f2f7-40f1-9d1e-66ce6e1accc0" title="Finite states">
  <img src="https://github.com/statelyai/xstate/assets/1093738/36d4b6b5-e3d0-4c19-9f41-2e3425ceac88" alt="Finite states" width="400" />
  <br />
  Open in Stately Studio
</a>
<br />

</td>
</tbody>
</table>

## Hierarchical (Nested) State Machines

<table>
<thead><tr><th>Code</th><th>Statechart</th></tr></thead>
<tbody>
<tr>
<td>

```js
import { createMachine, createActor } from 'xstate';

const pedestrianStates = {
  initial: 'walk',
  states: {
    walk: {
      on: {
        PED_TIMER: 'wait'
      }
    },
    wait: {
      on: {
        PED_TIMER: 'stop'
      }
    },
    stop: {}
  }
};

const lightMachine = createMachine({
  id: 'light',
  initial: 'green',
  states: {
    green: {
      on: {
        TIMER: 'yellow'
      }
    },
    yellow: {
      on: {
        TIMER: 'red'
      }
    },
    red: {
      on: {
        TIMER: 'green'
      },
      ...pedestrianStates
    }
  }
});

const actor = createActor(lightMachine);

actor.subscribe((state) => {
  console.log(state.value);
});

actor.start();
// logs 'green'

actor.send({ type: 'TIMER' });
// logs 'yellow'

actor.send({ type: 'TIMER' });
// logs { red: 'walk' }

actor.send({ type: 'PED_TIMER' });
// logs { red: 'wait' }
```

</td>
<td>
<a href="https://stately.ai/registry/editor/fa443471-b416-4014-8e6f-12417863e4d4?mode=design&machineId=30dffcdd-16c2-49e2-bfc6-a674057cb271" title="Hierarchical states">
  <img src="https://github.com/statelyai/xstate/assets/1093738/32b0692b-1c29-4469-b5e3-03146e3ef249" alt="Hierarchical states" width="400" />
  <br />
  Open in Stately Studio
</a>
<br />
</td>
</tr>
</tbody>
</table>

## Parallel State Machines

<table>
<thead><tr><th>Code</th><th>Statechart</th></tr></thead>
<tbody>
<tr>
<td>

```ts
import { createMachine, createActor } from 'xstate';

const wordMachine = createMachine({
  id: 'word',
  type: 'parallel',
  states: {
    bold: {
      initial: 'off',
      states: {
        on: {
          on: { TOGGLE_BOLD: 'off' }
        },
        off: {
          on: { TOGGLE_BOLD: 'on' }
        }
      }
    },
    underline: {
      initial: 'off',
      states: {
        on: {
          on: { TOGGLE_UNDERLINE: 'off' }
        },
        off: {
          on: { TOGGLE_UNDERLINE: 'on' }
        }
      }
    },
    italics: {
      initial: 'off',
      states: {
        on: {
          on: { TOGGLE_ITALICS: 'off' }
        },
        off: {
          on: { TOGGLE_ITALICS: 'on' }
        }
      }
    },
    list: {
      initial: 'none',
      states: {
        none: {
          on: {
            BULLETS: 'bullets',
            NUMBERS: 'numbers'
          }
        },
        bullets: {
          on: {
            NONE: 'none',
            NUMBERS: 'numbers'
          }
        },
        numbers: {
          on: {
            BULLETS: 'bullets',
            NONE: 'none'
          }
        }
      }
    }
  }
});

const actor = createActor(wordMachine);

actor.subscribe((state) => {
  console.log(state.value);
});

actor.start();
// logs {
//   bold: 'off',
//   italics: 'off',
//   underline: 'off',
//   list: 'none'
// }

actor.send({ type: 'TOGGLE_BOLD' });
// logs {
//   bold: 'on',
//   italics: 'off',
//   underline: 'off',
//   list: 'none'
// }

actor.send({ type: 'TOGGLE_ITALICS' });
// logs {
//   bold: 'on',
//   italics: 'on',
//   underline: 'off',
//   list: 'none'
// }
```

</td>
<td>
<a href="https://stately.ai/registry/editor/fa443471-b416-4014-8e6f-12417863e4d4?mode=design&machineId=980f50d8-e1ff-4441-8c8b-afe41c1610f2" title="Parallel states">
  <img src="https://github.com/statelyai/xstate/assets/1093738/3b1989c0-f4a9-4653-baf2-4df3a40e91a6" alt="Parallel states" width="400" />
  <br />
  Open in Stately Studio
</a>
</td>
</tr>
</tbody>
</table>

## History States

<table>
<thead><tr><th>Code</th><th>Statechart</th></tr></thead>
<tbody>
<tr>
<td>

```js
import { createMachine, createActor } from 'xstate';

const paymentMachine = createMachine({
  id: 'payment',
  initial: 'method',
  states: {
    method: {
      initial: 'cash',
      states: {
        cash: {
          on: {
            SWITCH_CHECK: 'check'
          }
        },
        check: {
          on: {
            SWITCH_CASH: 'cash'
          }
        },
        hist: { type: 'history' }
      },
      on: { NEXT: 'review' }
    },
    review: {
      on: { PREVIOUS: 'method.hist' }
    }
  }
});

const actor = createActor(paymentMachine);

actor.subscribe((state) => {
  console.log(state.value);
});

actor.start();
// logs {
//   value: { method: 'cash' },
// }

actor.send({ type: 'SWITCH_CHECK' });
// logs {
//   value: { method: 'check' },
// }

actor.send({ type: 'NEXT' });
// logs {
//   value: 'review',
// }

actor.send({ type: 'PREVIOUS' });
// logs {
//   value: { method: 'check' },
// }
```

</td>
<td>
<a href="https://stately.ai/registry/editor/fa443471-b416-4014-8e6f-12417863e4d4?mode=design&machineId=d1a9bb95-db97-4af3-b38b-71b005c643d3" title="History states">
  <img src="https://github.com/statelyai/xstate/assets/1093738/1be5c495-d560-4660-94f2-5341efbf7128" alt="History state" width="400" />
  <br />
  Open in Stately Studio
</a>
</td>
</tr>
</tbody>
</table>

## Sponsors

Special thanks to the sponsors who support this open-source project:

<img src="https://opencollective.com/xstate/tiers/backer/badge.svg?label=sponsors&color=brightgreen" />

<a href="https://transloadit.com/?utm_source=xstate&utm_medium=referral&utm_campaign=sponsorship&utm_content=github">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://assets.transloadit.com/assets/images/sponsorships/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://assets.transloadit.com/assets/images/sponsorships/logo-default.svg">
    <img src="https://assets.transloadit.com/assets/images/sponsorships/logo-default.svg" alt="Transloadit Logo">
  </picture>
</a>

## SemVer Policy

We understand the importance of the public contract and do not intend to release any breaking changes to the **runtime** API in a minor or patch release. We consider this with any changes we make to the XState libraries and aim to minimize their effects on existing users.

### Breaking changes

XState executes much of the user logic itself. Therefore, almost any change to its behavior might be considered a breaking change. We recognize this as a potential problem but believe that treating every change as a breaking change is not practical. We do our best to implement new features thoughtfully to enable our users to implement their logic in a better, safer way.

Any change _could_ affect how existing XState machines behave if those machines are using particular configurations. We do not introduce behavior changes on a whim and aim to avoid making changes that affect most existing machines. But we reserve the right to make _some_ behavior changes in minor releases. Our best judgment of the situation will always dictate such changes. Please always read our release notes before deciding to upgrade.

### TypeScript changes

We also reserve a similar right to adjust declared TypeScript definitions or drop support for older versions of TypeScript in a minor release. The TypeScript language itself evolves quickly and often introduces breaking changes in its minor releases. Our team is also continuously learning how to leverage TypeScript more effectively - and the types improve as a result.

For these reasons, it is impractical for our team to be bound by decisions taken when an older version of TypeScript was its latest version or when we didn’t know how to declare our types in a better way. We won’t introduce declaration changes often - but we are more likely to do so than with runtime changes.

### Packages

Most of the packages in the XState family declare a peer dependency on XState itself. We’ll be cautious about maintaining compatibility with already-released packages when releasing a new version of XState, **but** each release of packages depending on XState will always adjust the declared peer dependency range to include the latest version of XState. For example, you should always be able to update `xstate` without `@xstate/react`. But when you update `@xstate/react`, we highly recommend updating `xstate` too.
