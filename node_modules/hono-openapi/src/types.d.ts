import type { Context, Env, Input } from "hono";
import type { BlankInput } from "hono/types";
import type { ClientErrorStatusCode, ServerErrorStatusCode } from "hono/utils/http-status";
import type { OpenAPIV3 } from "openapi-types";
import type { ALLOWED_METHODS } from "./helper.js";
export type HasUndefined<T> = undefined extends T ? true : false;
export type PromiseOr<T> = T | Promise<T>;
export type OpenAPIRouteHandlerConfig = {
    version: "3.0.0" | "3.0.1" | "3.0.2" | "3.0.3" | "3.1.0";
    components: OpenAPIV3.ComponentsObject["schemas"];
} & {
    [key: string]: unknown;
};
export type ResolverResult = {
    builder: (options?: OpenAPIRouteHandlerConfig) => PromiseOr<{
        schema: OpenAPIV3.SchemaObject | OpenAPIV3.ReferenceObject;
        components?: OpenAPIV3.ComponentsObject["schemas"];
    }>;
    validator: (values: unknown) => PromiseOr<void>;
};
export type HandlerResponse = {
    resolver: (config: OpenAPIRouteHandlerConfig, defaultOptions?: DescribeRouteOptions) => PromiseOr<{
        docs: OpenAPIV3.OperationObject;
        components?: OpenAPIV3.ComponentsObject["schemas"];
    }>;
    metadata?: Record<string, unknown>;
};
export type DescribeRouteOptions = Omit<OpenAPIV3.OperationObject, "responses" | "parameters"> & {
    /**
     * Pass `true` to hide route from OpenAPI/swagger document
     */
    hide?: boolean | (<E extends Env = Env, P extends string = string, I extends Input = BlankInput>(c: Context<E, P, I>) => boolean);
    /**
     * Validate response of the route
     */
    validateResponse?: boolean | {
        status: ClientErrorStatusCode | ServerErrorStatusCode;
        message?: string;
    };
    /**
     * Responses of the request
     */
    responses?: {
        [key: string]: (OpenAPIV3.ResponseObject & {
            content?: {
                [key: string]: Omit<OpenAPIV3.MediaTypeObject, "schema"> & {
                    schema?: OpenAPIV3.ReferenceObject | OpenAPIV3.SchemaObject | ResolverResult;
                };
            };
        }) | OpenAPIV3.ReferenceObject;
    };
    /**
     * Parameters of the request
     */
    parameters?: (OpenAPIV3.ParameterObject | (OpenAPIV3.ParameterObject & {
        schema: ResolverResult;
    }))[];
};
export interface OpenAPIRoute {
    path: string;
    method: (typeof ALLOWED_METHODS)[number] | "ALL";
    data?: DescribeRouteOptions | Pick<OpenAPIV3.OperationObject, "parameters" | "requestBody">;
}
export type OpenApiSpecsOptions = {
    /**
     * Customize OpenAPI config, refers to Swagger 2.0 config
     *
     * @see https://swagger.io/specification/v2/
     */
    documentation?: Omit<Partial<OpenAPIV3.Document>, "x-express-openapi-additional-middleware" | "x-express-openapi-validation-strict">;
    /**
     * Include paths which don't have the handlers.
     * This is useful when you want to document the
     * API without implementing it or index all the paths.
     */
    includeEmptyPaths?: boolean;
    /**
     * Determine if Swagger should exclude static files.
     *
     * @default true
     */
    excludeStaticFile?: boolean;
    /**
     * Paths to exclude from OpenAPI endpoint
     *
     * @default []
     */
    exclude?: string | RegExp | Array<string | RegExp>;
    /**
     * Exclude methods from Open API
     */
    excludeMethods?: (typeof ALLOWED_METHODS)[number][];
    /**
     * Exclude tags from OpenAPI
     */
    excludeTags?: string[];
    /**
     * Default options for `describeRoute` method
     */
    defaultOptions?: Partial<Record<(typeof ALLOWED_METHODS)[number] | "ALL", DescribeRouteOptions>>;
};
