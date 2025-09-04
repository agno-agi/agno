import type { JSONSchema, ParserOptions } from "@apidevtools/json-schema-ref-parser";
import type { JSONSchema4 } from "json-schema";
import type { OpenAPIV3 } from "openapi-types";
export type addPrefixToObject = {
    [K in keyof JSONSchema as `x-${K}`]: JSONSchema[K];
};
export interface Options {
    cloneSchema?: boolean;
    dereference?: boolean;
    convertUnreferencedDefinitions?: boolean;
    dereferenceOptions?: ParserOptions | undefined;
}
type ExtendedJSONSchema = addPrefixToObject & JSONSchema;
export type SchemaType = ExtendedJSONSchema & {
    example?: JSONSchema["examples"][number];
    "x-patternProperties"?: JSONSchema["patternProperties"];
    nullable?: boolean;
};
export type SchemaTypeKeys = keyof SchemaType;
declare const convert: <T extends object = JSONSchema4>(schema: T, options?: Options) => Promise<OpenAPIV3.Document>;
export default convert;
