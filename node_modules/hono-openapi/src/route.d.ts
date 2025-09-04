import type { MiddlewareHandler } from "hono/types";
import type { ClientErrorStatusCode, ServerErrorStatusCode } from "hono/utils/http-status";
import type { DescribeRouteOptions, OpenAPIRouteHandlerConfig } from "./types.js";
/**
 * Describe a route with OpenAPI specs.
 * @param specs Options for describing a route
 * @returns Middleware handler
 */
export declare function describeRoute(specs: DescribeRouteOptions): MiddlewareHandler;
/**
 * Generate OpenAPI specs for the given route
 * @param config Route handler configuration
 * @param docs Route description in OpenAPI specs
 * @param defaultOptions Default options for describing a route
 */
export declare function generateRouteSpecs(config: OpenAPIRouteHandlerConfig, docs: DescribeRouteOptions, defaultOptions?: DescribeRouteOptions): Promise<{
    docs: {
        responses: {
            [x: string]: import("openapi-types").OpenAPIV3.ReferenceObject | (import("openapi-types").OpenAPIV3.ResponseObject & {
                content?: {
                    [key: string]: Omit<import("openapi-types").OpenAPIV3.MediaTypeObject, "schema"> & {
                        schema?: import("openapi-types").OpenAPIV3.ReferenceObject | import("openapi-types").OpenAPIV3.SchemaObject | import("./types.js").ResolverResult;
                    };
                };
            });
        };
        tags?: string[];
        summary?: string;
        description?: string;
        externalDocs?: import("openapi-types").OpenAPIV3.ExternalDocumentationObject;
        operationId?: string;
        requestBody?: import("openapi-types").OpenAPIV3.ReferenceObject | import("openapi-types").OpenAPIV3.RequestBodyObject;
        callbacks?: {
            [callback: string]: import("openapi-types").OpenAPIV3.ReferenceObject | import("openapi-types").OpenAPIV3.CallbackObject;
        };
        deprecated?: boolean;
        security?: import("openapi-types").OpenAPIV3.SecurityRequirementObject[];
        servers?: import("openapi-types").OpenAPIV3.ServerObject[];
        hide?: boolean | (<E extends import("hono").Env = import("hono").Env, P extends string = string, I extends import("hono").Input = import("hono/types").BlankInput>(c: import("hono").Context<E, P, I>) => boolean);
        validateResponse?: boolean | {
            status: ClientErrorStatusCode | ServerErrorStatusCode;
            message?: string;
        };
        parameters?: (import("openapi-types").OpenAPIV3.ParameterObject | (import("openapi-types").OpenAPIV3.ParameterObject & {
            schema: import("./types.js").ResolverResult;
        }))[];
    };
    components: {};
}>;
