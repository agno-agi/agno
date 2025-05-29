import { NextResponse } from 'next/server';
import { readdir, stat } from 'fs/promises';
import { join, relative } from 'path';
import { FileEntry } from '@/components/file-tree/file-tree';

async function buildFileTree(dir: string, rootPath: string): Promise<FileEntry[]> {
  const entries = await readdir(dir);
  const result: FileEntry[] = [];

  for (const entry of entries) {
    const fullPath = join(dir, entry);
    const stats = await stat(fullPath);
    // Make paths relative to the demo's root path
    const relativePath = '/' + relative(rootPath, fullPath);

    if (stats.isDirectory()) {
      result.push({
        name: entry,
        path: relativePath,
        type: 'directory',
        content: '',
        children: await buildFileTree(fullPath, rootPath),
      });
    } else {
      result.push({
        name: entry,
        path: relativePath,
        content: '',
        type: 'file',
      });
    }
  }

  return result.sort((a, b) => {
    // Directories first, then files
    if (a.type === 'directory' && b.type === 'file') return -1;
    if (a.type === 'file' && b.type === 'directory') return 1;
    return a.name.localeCompare(b.name);
  });
}

export async function POST(request: Request) {
  try {
    const { path } = await request.json();
    console.log('Requested path:', path);
    
    // Remove leading slash if present to make path relative
    const relativePath = path.startsWith('/') ? path.slice(1) : path;
    const absolutePath = join(process.cwd(), relativePath);
    console.log('Resolved absolute path:', absolutePath);
    
    // Use the requested path as the root for relative paths
    const files = await buildFileTree(absolutePath, absolutePath);
    console.log('Found files:', files);
    
    return NextResponse.json({ files });
  } catch (error) {
    console.error('Error listing directory:', error);
    return NextResponse.json(
      { error: 'Failed to list directory' },
      { status: 500 }
    );
  }
} 