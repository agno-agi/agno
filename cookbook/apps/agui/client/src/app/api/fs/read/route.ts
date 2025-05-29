import { NextResponse } from 'next/server';
import { readFile } from 'fs/promises';
import { join } from 'path';

export async function POST(request: Request) {
  try {
    const { path } = await request.json();
    console.log('Requested file path:', path);
    
    // Remove leading slash if present to make path relative
    const relativePath = path.startsWith('/') ? path.slice(1) : path;
    const absolutePath = join(process.cwd(), relativePath);
    console.log('Resolved absolute file path:', absolutePath);
    
    const content = await readFile(absolutePath, 'utf-8');
    console.log('File content length:', content.length);
    
    return NextResponse.json({ content });
  } catch (error) {
    console.error('Error reading file:', error);
    return NextResponse.json(
      { error: 'Failed to read file' },
      { status: 500 }
    );
  }
} 