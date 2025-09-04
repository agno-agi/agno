export interface Options {
	/**
	@default '-'

	@example
	```
	import slugify from '@sindresorhus/slugify';

	slugify('BAR and baz');
	//=> 'bar-and-baz'

	slugify('BAR and baz', {separator: '_'});
	//=> 'bar_and_baz'

	slugify('BAR and baz', {separator: ''});
	//=> 'barandbaz'
	```
	*/
	readonly separator?: string;

	/**
	Make the slug lowercase.

	@default true

	@example
	```
	import slugify from '@sindresorhus/slugify';

	slugify('Déjà Vu!');
	//=> 'deja-vu'

	slugify('Déjà Vu!', {lowercase: false});
	//=> 'Deja-Vu'
	```
	*/
	readonly lowercase?: boolean;

	/**
	Convert camelcase to separate words. Internally it does `fooBar` → `foo bar`.

	@default true

	@example
	```
	import slugify from '@sindresorhus/slugify';

	slugify('fooBar');
	//=> 'foo-bar'

	slugify('fooBar', {decamelize: false});
	//=> 'foobar'
	```
	*/
	readonly decamelize?: boolean;

	/**
	Add your own custom replacements.

	The replacements are run on the original string before any other transformations.

	This only overrides a default replacement if you set an item with the same key, like `&`.

	Add a leading and trailing space to the replacement to have it separated by dashes.

	@default [ ['&', ' and '], ['🦄', ' unicorn '], ['♥', ' love '] ]

	@example
	```
	import slugify from '@sindresorhus/slugify';

	slugify('Foo@unicorn', {
		customReplacements: [
			['@', 'at']
		]
	});
	//=> 'fooatunicorn'

	slugify('foo@unicorn', {
		customReplacements: [
			['@', ' at ']
		]
	});
	//=> 'foo-at-unicorn'

	slugify('I love 🐶', {
		customReplacements: [
			['🐶', 'dogs']
		]
	});
	//=> 'i-love-dogs'
	```
	*/
	readonly customReplacements?: ReadonlyArray<[string, string]>;

	/**
	If your string starts with an underscore, it will be preserved in the slugified string.

	Sometimes leading underscores are intentional, for example, filenames representing hidden paths on a website.

	@default false

	@example
	```
	import slugify from '@sindresorhus/slugify';

	slugify('_foo_bar');
	//=> 'foo-bar'

	slugify('_foo_bar', {preserveLeadingUnderscore: true});
	//=> '_foo-bar'
	```
	*/
	readonly preserveLeadingUnderscore?: boolean;

	/**
	If your string ends with a dash, it will be preserved in the slugified string.

	For example, using slugify on an input field would allow for validation while not preventing the user from writing a slug.

	@default false

	@example
	```
	import slugify from '@sindresorhus/slugify';

	slugify('foo-bar-');
	//=> 'foo-bar'

	slugify('foo-bar-', {preserveTrailingDash: true});
	//=> 'foo-bar-'
	```
	 */
	readonly preserveTrailingDash?: boolean;

	/**
	Preserve certain characters.

	It cannot contain the `separator`.

	For example, if you want to slugify URLs, but preserve the HTML fragment `#` character, you could set `preserveCharacters: ['#']`.

	@default []

	@example
	```
	import slugify from '@sindresorhus/slugify';

	slugify('foo_bar#baz', {preserveCharacters: ['#']});
	//=> 'foo-bar#baz'
	```
	*/
	readonly preserveCharacters?: string[];
}

/**
Slugify a string.

@param string - String to slugify.

@example
```
import slugify from '@sindresorhus/slugify';

slugify('I ♥ Dogs');
//=> 'i-love-dogs'

slugify('  Déjà Vu!  ');
//=> 'deja-vu'

slugify('fooBar 123 $#%');
//=> 'foo-bar-123'

slugify('я люблю единорогов');
//=> 'ya-lyublyu-edinorogov'
```
*/
export default function slugify(string: string, options?: Options): string;

export interface CountableSlugify {
	/**
	Reset the counter.

	@example
	```
	import {slugifyWithCounter} from '@sindresorhus/slugify';

	const slugify = slugifyWithCounter();

	slugify('foo bar');
	//=> 'foo-bar'

	slugify('foo bar');
	//=> 'foo-bar-2'

	slugify.reset();

	slugify('foo bar');
	//=> 'foo-bar'
	```
	*/
	reset: () => void;

	/**
	Returns a new instance of `slugify(string, options?)` with a counter to handle multiple occurrences of the same string.

	@param string - String to slugify.

	@example
	```
	import {slugifyWithCounter} from '@sindresorhus/slugify';

	const slugify = slugifyWithCounter();

	slugify('foo bar');
	//=> 'foo-bar'

	slugify('foo bar');
	//=> 'foo-bar-2'

	slugify.reset();

	slugify('foo bar');
	//=> 'foo-bar'
	```

	__Use case example of counter__

	If, for example, you have a document with multiple sections where each subsection has an example.

	```
	## Section 1

	### Example

	## Section 2

	### Example
	```

	You can then use `slugifyWithCounter()` to generate unique HTML `id`'s to ensure anchors will link to the right headline.
	*/
	(string: string, options?: Options): string;
}

export function slugifyWithCounter(): CountableSlugify;
