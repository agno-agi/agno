import { getHash, stripHash, toFileSystemPath } from "./url.js";
import type $RefParser from "../index.js";
import type { ParserOptions } from "../index.js";
import type { JSONSchema } from "../index.js";
import type $Ref from "../ref";

export type JSONParserErrorType =
  | "EUNKNOWN"
  | "EPARSER"
  | "EUNMATCHEDPARSER"
  | "ETIMEOUT"
  | "ERESOLVER"
  | "EUNMATCHEDRESOLVER"
  | "EMISSINGPOINTER"
  | "EINVALIDPOINTER";
const nonJsonTypes = ["function", "symbol", "undefined"];
const protectedProps = ["constructor", "prototype", "__proto__"];
const objectPrototype = Object.getPrototypeOf({});

/**
 * Custom JSON serializer for Error objects.
 * Returns all built-in error properties, as well as extended properties.
 */
export function toJSON<T extends Error>(this: T): Error & T {
  // HACK: We have to cast the objects to `any` so we can use symbol indexers.
  // see https://github.com/Microsoft/TypeScript/issues/1863
  const pojo: any = {};
  const error = this as any;

  for (const key of getDeepKeys(error)) {
    if (typeof key === "string") {
      const value = error[key];
      const type = typeof value;

      if (!nonJsonTypes.includes(type)) {
        pojo[key] = value;
      }
    }
  }

  return pojo as Error & T;
}

/**
 * Returns own, inherited, enumerable, non-enumerable, string, and symbol keys of `obj`.
 * Does NOT return members of the base Object prototype, or the specified omitted keys.
 */
export function getDeepKeys(obj: object, omit: Array<string | symbol> = []): Set<string | symbol> {
  let keys: Array<string | symbol> = [];

  // Crawl the prototype chain, finding all the string and symbol keys
  while (obj && obj !== objectPrototype) {
    keys = keys.concat(Object.getOwnPropertyNames(obj), Object.getOwnPropertySymbols(obj));
    obj = Object.getPrototypeOf(obj) as object;
  }

  // De-duplicate the list of keys
  const uniqueKeys = new Set(keys);

  // Remove any omitted keys
  for (const key of omit.concat(protectedProps)) {
    uniqueKeys.delete(key);
  }

  return uniqueKeys;
}
export class JSONParserError extends Error {
  public readonly name: string;
  public readonly message: string;
  public source: string | undefined;
  public path: Array<string | number> | null;
  public readonly code: JSONParserErrorType;
  public constructor(message: string, source?: string) {
    super();

    this.code = "EUNKNOWN";
    this.name = "JSONParserError";
    this.message = message;
    this.source = source;
    this.path = null;
  }

  toJSON = toJSON.bind(this);

  get footprint() {
    return `${this.path}+${this.source}+${this.code}+${this.message}`;
  }
}

export class JSONParserErrorGroup<
  S extends object = JSONSchema,
  O extends ParserOptions<S> = ParserOptions<S>,
> extends Error {
  files: $RefParser<S, O>;

  constructor(parser: $RefParser<S, O>) {
    super();

    this.files = parser;
    this.name = "JSONParserErrorGroup";
    this.message = `${this.errors.length} error${
      this.errors.length > 1 ? "s" : ""
    } occurred while reading '${toFileSystemPath(parser.$refs._root$Ref!.path)}'`;
  }
  toJSON = toJSON.bind(this);

  static getParserErrors<S extends object = JSONSchema, O extends ParserOptions<S> = ParserOptions<S>>(
    parser: $RefParser<S, O>,
  ) {
    const errors = [];

    for (const $ref of Object.values(parser.$refs._$refs) as $Ref<S, O>[]) {
      if ($ref.errors) {
        errors.push(...$ref.errors);
      }
    }

    return errors;
  }

  get errors(): Array<
    | JSONParserError
    | InvalidPointerError
    | ResolverError
    | ParserError
    | MissingPointerError
    | UnmatchedParserError
    | UnmatchedResolverError
  > {
    return JSONParserErrorGroup.getParserErrors<S, O>(this.files);
  }
}

export class ParserError extends JSONParserError {
  code = "EPARSER" as JSONParserErrorType;
  name = "ParserError";
  constructor(message: any, source: any) {
    super(`Error parsing ${source}: ${message}`, source);
  }
}

export class UnmatchedParserError extends JSONParserError {
  code = "EUNMATCHEDPARSER" as JSONParserErrorType;
  name = "UnmatchedParserError";

  constructor(source: string) {
    super(`Could not find parser for "${source}"`, source);
  }
}

export class ResolverError extends JSONParserError {
  code = "ERESOLVER" as JSONParserErrorType;
  name = "ResolverError";
  ioErrorCode?: string;
  constructor(ex: Error | any, source?: string) {
    super(ex.message || `Error reading file "${source}"`, source);
    if ("code" in ex) {
      this.ioErrorCode = String(ex.code);
    }
  }
}

export class UnmatchedResolverError extends JSONParserError {
  code = "EUNMATCHEDRESOLVER" as JSONParserErrorType;
  name = "UnmatchedResolverError";
  constructor(source: any) {
    super(`Could not find resolver for "${source}"`, source);
  }
}

export class MissingPointerError extends JSONParserError {
  code = "EMISSINGPOINTER" as JSONParserErrorType;
  name = "MissingPointerError";
  public targetToken: any;
  public targetRef: string;
  public targetFound: string;
  public parentPath: string;
  constructor(token: any, path: any, targetRef: any, targetFound: any, parentPath: any) {
    super(`Missing $ref pointer "${getHash(path)}". Token "${token}" does not exist.`, stripHash(path));

    this.targetToken = token;
    this.targetRef = targetRef;
    this.targetFound = targetFound;
    this.parentPath = parentPath;
  }
}

export class TimeoutError extends JSONParserError {
  code = "ETIMEOUT" as JSONParserErrorType;
  name = "TimeoutError";
  constructor(timeout: number) {
    super(`Dereferencing timeout reached: ${timeout}ms`);
  }
}

export class InvalidPointerError extends JSONParserError {
  code = "EUNMATCHEDRESOLVER" as JSONParserErrorType;
  name = "InvalidPointerError";
  constructor(pointer: string, path: string) {
    super(`Invalid $ref pointer "${pointer}". Pointers must begin with "#/"`, stripHash(path));
  }
}

export function isHandledError(err: any): err is JSONParserError {
  return err instanceof JSONParserError || err instanceof JSONParserErrorGroup;
}

export function normalizeError(err: any) {
  if (err.path === null) {
    err.path = [];
  }

  return err;
}
