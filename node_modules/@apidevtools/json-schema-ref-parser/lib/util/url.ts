import convertPathToPosix from "./convert-path-to-posix";
import path, { win32 } from "path";

const forwardSlashPattern = /\//g;
const protocolPattern = /^(\w{2,}):\/\//i;
const jsonPointerSlash = /~1/g;
const jsonPointerTilde = /~0/g;

import { join } from "path";
import { isWindows } from "./is-windows";

// RegExp patterns to URL-encode special characters in local filesystem paths
const urlEncodePatterns = [
  [/\?/g, "%3F"],
  [/#/g, "%23"],
] as [RegExp, string][];

// RegExp patterns to URL-decode special characters for local filesystem paths
const urlDecodePatterns = [/%23/g, "#", /%24/g, "$", /%26/g, "&", /%2C/g, ",", /%40/g, "@"];

export const parse = (u: string | URL) => new URL(u);

/**
 * Returns resolved target URL relative to a base URL in a manner similar to that of a Web browser resolving an anchor tag HREF.
 *
 * @returns
 */
export function resolve(from: string, to: string) {
  // we use a non-existent URL to check if its a relative URL
  const fromUrl = new URL(convertPathToPosix(from), "https://aaa.nonexistanturl.com");
  const resolvedUrl = new URL(convertPathToPosix(to), fromUrl);
  const endSpaces = to.match(/(\s*)$/)?.[1] || "";
  if (resolvedUrl.hostname === "aaa.nonexistanturl.com") {
    // `from` is a relative URL.
    const { pathname, search, hash } = resolvedUrl;
    return pathname + search + hash + endSpaces;
  }
  return resolvedUrl.toString() + endSpaces;
}

/**
 * Returns the current working directory (in Node) or the current page URL (in browsers).
 *
 * @returns
 */
export function cwd() {
  if (typeof window !== "undefined" && window.location && window.location.href) {
    const href = window.location.href;
    if (!href || !href.startsWith("http")) {
      // try parsing as url, and if it fails, return root url /
      try {
        new URL(href);
        return href;
      } catch {
        return "/";
      }
    }
    return href;
  }

  if (typeof process !== "undefined" && process.cwd) {
    const path = process.cwd();

    const lastChar = path.slice(-1);
    if (lastChar === "/" || lastChar === "\\") {
      return path;
    } else {
      return path + "/";
    }
  }
  return "/";
}

/**
 * Returns the protocol of the given URL, or `undefined` if it has no protocol.
 *
 * @param path
 * @returns
 */
export function getProtocol(path: string | undefined) {
  const match = protocolPattern.exec(path || "");
  if (match) {
    return match[1].toLowerCase();
  }
  return undefined;
}

/**
 * Returns the lowercased file extension of the given URL,
 * or an empty string if it has no extension.
 *
 * @param path
 * @returns
 */
export function getExtension(path: any) {
  const lastDot = path.lastIndexOf(".");
  if (lastDot >= 0) {
    return stripQuery(path.substring(lastDot).toLowerCase());
  }
  return "";
}

/**
 * Removes the query, if any, from the given path.
 *
 * @param path
 * @returns
 */
export function stripQuery(path: any) {
  const queryIndex = path.indexOf("?");
  if (queryIndex >= 0) {
    path = path.substring(0, queryIndex);
  }
  return path;
}

/**
 * Returns the hash (URL fragment), of the given path.
 * If there is no hash, then the root hash ("#") is returned.
 *
 * @param path
 * @returns
 */
export function getHash(path: undefined | string) {
  if (!path) {
    return "#";
  }
  const hashIndex = path.indexOf("#");
  if (hashIndex >= 0) {
    return path.substring(hashIndex);
  }
  return "#";
}

/**
 * Removes the hash (URL fragment), if any, from the given path.
 *
 * @param path
 * @returns
 */
export function stripHash(path?: string | undefined) {
  if (!path) {
    return "";
  }
  const hashIndex = path.indexOf("#");
  if (hashIndex >= 0) {
    path = path.substring(0, hashIndex);
  }
  return path;
}

/**
 * Determines whether the given path is an HTTP(S) URL.
 *
 * @param path
 * @returns
 */
export function isHttp(path: string) {
  const protocol = getProtocol(path);
  if (protocol === "http" || protocol === "https") {
    return true;
  } else if (protocol === undefined) {
    // There is no protocol.  If we're running in a browser, then assume it's HTTP.
    return typeof window !== "undefined";
  } else {
    // It's some other protocol, such as "ftp://", "mongodb://", etc.
    return false;
  }
}
/**
 * Determines whether the given url is an unsafe or internal url.
 *
 * @param path - The URL or path to check
 * @returns true if the URL is unsafe/internal, false otherwise
 */
export function isUnsafeUrl(path: string | unknown): boolean {
  if (!path || typeof path !== "string") {
    return true;
  }

  // Trim whitespace and convert to lowercase for comparison
  const normalizedPath = path.trim().toLowerCase();

  // Empty or just whitespace
  if (!normalizedPath) {
    return true;
  }

  // JavaScript protocols
  if (
    normalizedPath.startsWith("javascript:") ||
    normalizedPath.startsWith("vbscript:") ||
    normalizedPath.startsWith("data:")
  ) {
    return true;
  }

  // File protocol
  if (normalizedPath.startsWith("file:")) {
    return true;
  }

  // if we're in the browser, we assume that it is safe
  if (typeof window !== "undefined" && window.location && window.location.href) {
    return false;
  }

  // Local/internal network addresses
  const localPatterns = [
    // Localhost variations
    "localhost",
    "127.0.0.1",
    "::1",

    // Private IP ranges (RFC 1918)
    "10.",
    "172.16.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
    "192.168.",

    // Link-local addresses
    "169.254.",

    // Internal domains
    ".local",
    ".internal",
    ".intranet",
    ".corp",
    ".home",
    ".lan",
  ];

  try {
    // Try to parse as URL
    const url = new URL(normalizedPath.startsWith("//") ? "http:" + normalizedPath : normalizedPath);

    const hostname = url.hostname.toLowerCase();

    // Check against local patterns
    for (const pattern of localPatterns) {
      if (hostname === pattern || hostname.startsWith(pattern) || hostname.endsWith(pattern)) {
        return true;
      }
    }

    // Check for IP addresses in private ranges
    if (isPrivateIP(hostname)) {
      return true;
    }

    // Check for non-standard ports that might indicate internal services
    const port = url.port;
    if (port && isInternalPort(parseInt(port))) {
      return true;
    }
  } catch {
    // If URL parsing fails, check if it's a relative path or contains suspicious patterns

    // Relative paths starting with / are generally safe for same-origin
    if (normalizedPath.startsWith("/") && !normalizedPath.startsWith("//")) {
      return false;
    }

    // Check for localhost patterns in non-URL strings
    for (const pattern of localPatterns) {
      if (normalizedPath.includes(pattern)) {
        return true;
      }
    }
  }

  return false;
}

/**
 * Helper function to check if an IP address is in a private range
 */
function isPrivateIP(ip: string): boolean {
  const ipRegex = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;
  const match = ip.match(ipRegex);

  if (!match) {
    return false;
  }

  const [, a, b, c, d] = match.map(Number);

  // Validate IP format
  if (a > 255 || b > 255 || c > 255 || d > 255) {
    return false;
  }

  // Private IP ranges
  return (
    a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 169 && b === 254) // Link-local
  );
}

/**
 * Helper function to check if a port is typically used for internal services
 */
function isInternalPort(port: number): boolean {
  const internalPorts = [
    22, // SSH
    23, // Telnet
    25, // SMTP
    53, // DNS
    135, // RPC
    139, // NetBIOS
    445, // SMB
    993, // IMAPS
    995, // POP3S
    1433, // SQL Server
    1521, // Oracle
    3306, // MySQL
    3389, // RDP
    5432, // PostgreSQL
    5900, // VNC
    6379, // Redis
    8080, // Common internal web
    8443, // Common internal HTTPS
    9200, // Elasticsearch
    27017, // MongoDB
  ];

  return internalPorts.includes(port);
}
/**
 * Determines whether the given path is a filesystem path.
 * This includes "file://" URLs.
 *
 * @param path
 * @returns
 */
export function isFileSystemPath(path: string | undefined) {
  // @ts-ignore
  if (typeof window !== "undefined" || (typeof process !== "undefined" && process.browser)) {
    // We're running in a browser, so assume that all paths are URLs.
    // This way, even relative paths will be treated as URLs rather than as filesystem paths
    return false;
  }

  const protocol = getProtocol(path);
  return protocol === undefined || protocol === "file";
}

/**
 * Converts a filesystem path to a properly-encoded URL.
 *
 * This is intended to handle situations where JSON Schema $Ref Parser is called
 * with a filesystem path that contains characters which are not allowed in URLs.
 *
 * @example
 * The following filesystem paths would be converted to the following URLs:
 *
 *    <"!@#$%^&*+=?'>.json              ==>   %3C%22!@%23$%25%5E&*+=%3F\'%3E.json
 *    C:\\My Documents\\File (1).json   ==>   C:/My%20Documents/File%20(1).json
 *    file://Project #42/file.json      ==>   file://Project%20%2342/file.json
 *
 * @param path
 * @returns
 */
export function fromFileSystemPath(path: string) {
  // Step 1: On Windows, replace backslashes with forward slashes,
  // rather than encoding them as "%5C"
  if (isWindows()) {
    const projectDir = cwd();
    const upperPath = path.toUpperCase();
    const projectDirPosixPath = convertPathToPosix(projectDir);
    const posixUpper = projectDirPosixPath.toUpperCase();
    const hasProjectDir = upperPath.includes(posixUpper);
    const hasProjectUri = upperPath.includes(posixUpper);
    const isAbsolutePath =
      win32?.isAbsolute(path) ||
      path.startsWith("http://") ||
      path.startsWith("https://") ||
      path.startsWith("file://");

    if (!(hasProjectDir || hasProjectUri || isAbsolutePath) && !projectDir.startsWith("http")) {
      path = join(projectDir, path);
    }
    path = convertPathToPosix(path);
  }

  // Step 2: `encodeURI` will take care of MOST characters
  path = encodeURI(path);

  // Step 3: Manually encode characters that are not encoded by `encodeURI`.
  // This includes characters such as "#" and "?", which have special meaning in URLs,
  // but are just normal characters in a filesystem path.
  for (const pattern of urlEncodePatterns) {
    path = path.replace(pattern[0], pattern[1]);
  }

  return path;
}

/**
 * Converts a URL to a local filesystem path.
 */
export function toFileSystemPath(path: string | undefined, keepFileProtocol?: boolean): string {
  // Step 1: `decodeURI` will decode characters such as Cyrillic characters, spaces, etc.
  path = decodeURI(path!);

  // Step 2: Manually decode characters that are not decoded by `decodeURI`.
  // This includes characters such as "#" and "?", which have special meaning in URLs,
  // but are just normal characters in a filesystem path.
  for (let i = 0; i < urlDecodePatterns.length; i += 2) {
    path = path.replace(urlDecodePatterns[i], urlDecodePatterns[i + 1] as string);
  }

  // Step 3: If it's a "file://" URL, then format it consistently
  // or convert it to a local filesystem path
  let isFileUrl = path.toLowerCase().startsWith("file://");
  if (isFileUrl) {
    // Strip-off the protocol, and the initial "/", if there is one
    path = path.replace(/^file:\/\//, "").replace(/^\//, "");

    // insert a colon (":") after the drive letter on Windows
    if (isWindows() && path[1] === "/") {
      path = `${path[0]}:${path.substring(1)}`;
    }

    if (keepFileProtocol) {
      // Return the consistently-formatted "file://" URL
      path = "file:///" + path;
    } else {
      // Convert the "file://" URL to a local filesystem path.
      // On Windows, it will start with something like "C:/".
      // On Posix, it will start with "/"
      isFileUrl = false;
      path = isWindows() ? path : "/" + path;
    }
  }

  // Step 4: Normalize Windows paths (unless it's a "file://" URL)
  if (isWindows() && !isFileUrl) {
    // Replace forward slashes with backslashes
    path = path.replace(forwardSlashPattern, "\\");

    // Capitalize the drive letter
    if (path.match(/^[a-z]:\\/i)) {
      path = path[0].toUpperCase() + path.substring(1);
    }
  }

  return path;
}

/**
 * Converts a $ref pointer to a valid JSON Path.
 *
 * @param pointer
 * @returns
 */
export function safePointerToPath(pointer: any) {
  if (pointer.length <= 1 || pointer[0] !== "#" || pointer[1] !== "/") {
    return [];
  }

  return pointer
    .slice(2)
    .split("/")
    .map((value: any) => {
      return decodeURIComponent(value).replace(jsonPointerSlash, "/").replace(jsonPointerTilde, "~");
    });
}

export function relative(from: string, to: string) {
  if (!isFileSystemPath(from) || !isFileSystemPath(to)) {
    return resolve(from, to);
  }

  const fromDir = path.dirname(stripHash(from));
  const toPath = stripHash(to);

  const result = path.relative(fromDir, toPath);
  return result + getHash(to);
}
