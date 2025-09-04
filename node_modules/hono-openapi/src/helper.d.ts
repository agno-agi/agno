import type { OpenAPIV3 } from "openapi-types";
import type { OpenAPIRoute, OpenApiSpecsOptions } from "./types.js";
export declare const ALLOWED_METHODS: readonly ["GET", "PUT", "POST", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"];
export declare const toOpenAPIPath: (path: string) => string;
export declare const capitalize: (word: string) => string;
export declare const generateOperationId: (method: string, paths: string) => string;
export declare function registerSchemaPath({ path, method: _method, data, schema, }: OpenAPIRoute & {
    schema: Partial<OpenAPIV3.PathsObject>;
}): void;
export declare function filterPaths(paths: OpenAPIV3.PathsObject, { excludeStaticFile, exclude, }: Pick<OpenApiSpecsOptions, "excludeStaticFile" | "exclude">): OpenAPIV3.PathsObject<{}, {}>;
