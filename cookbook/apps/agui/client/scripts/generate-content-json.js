const fs = require("fs");
const path = require("path");

// Files to include for each demo
const config = {
  agentic_chat: ["agent.py", "page.tsx", "style.css", "README.mdx"],
  agentic_generative_ui: ["agent.py", "page.tsx", "style.css", "README.mdx"],
  human_in_the_loop: ["agent.py", "page.tsx", "style.css", "README.mdx"],
  shared_state: ["agent.py", "page.tsx", "style.css", "README.mdx"],
  predictive_state_updates: ["agent.py", "page.tsx", "style.css", "README.mdx"],
  tool_based_generative_ui: ["agent.py", "page.tsx", "style.css", "README.mdx"],
};

// Define which files should come from the feature directory vs. the demo directory
const FEATURE_FILES = ["page.tsx", "style.css", "README.mdx", "code.tsx"];

const result = {};

for (const demo in config) {
  result[demo] = { files: [] };
  const files = config[demo];

  // Check if code.tsx exists and should be used as page.tsx
  let hasCodeTsx = false;
  let codeTsxContent = null;
  let codeTsxLanguage = "typescript";

  // First check for code.tsx in feature directory
  const codeTsxFeaturePath = path.join(
    __dirname,
    `../src/app/feature/${demo}/code.tsx`
  );
  if (fs.existsSync(codeTsxFeaturePath)) {
    try {
      codeTsxContent = fs.readFileSync(codeTsxFeaturePath, "utf8");
      hasCodeTsx = true;
    } catch (error) {
      console.warn(
        `Could not read code.tsx from feature directory:`,
        error.message
      );
    }
  }

  // If not found in feature directory, try demo directory
  if (!hasCodeTsx) {
    const codeTsxDemoPath = path.join(
      __dirname,
      `../agent/demo/${demo}/code.tsx`
    );
    if (fs.existsSync(codeTsxDemoPath)) {
      try {
        codeTsxContent = fs.readFileSync(codeTsxDemoPath, "utf8");
        hasCodeTsx = true;
      } catch (error) {
        console.warn(
          `Could not read code.tsx from demo directory:`,
          error.message
        );
      }
    }
  }

  // If we have code.tsx, add it as page.tsx immediately
  if (hasCodeTsx) {
    result[demo].files.push({
      name: "page.tsx",
      content: codeTsxContent,
      path: "page.tsx",
      language: "typescript",
    });
  }

  for (const file of files) {
    if (
      file.endsWith(".py") ||
      file.endsWith(".yaml") ||
      file.endsWith(".toml")
    ) {
      continue;
    }
    // Skip both page.tsx and code.tsx if we have code.tsx
    if (hasCodeTsx && (file === "page.tsx" || file === "code.tsx")) {
      continue;
    }

    let filePath;
    let content;

    // Determine where to read the file from
    if (FEATURE_FILES.includes(file) || file.endsWith("page.tsx")) {
      // Check if file exists in feature directory
      const featurePath = path.join(
        __dirname,
        `../src/app/feature/${demo}/${file}`
      );
      if (fs.existsSync(featurePath)) {
        filePath = featurePath;
      } else {
        // Fallback to demo directory if not found in feature
        filePath = path.join(__dirname, `../agent/demo/${demo}/${file}`);
      }
    } else {
      // Use demo directory for agent.py and other files
      filePath = path.join(__dirname, `../agent/demo/${demo}/${file}`);
    }

    try {
      content = fs.readFileSync(filePath, "utf8");
    } catch (error) {
      console.warn(`Could not read file ${filePath}:`, error.message);
      continue; // Skip this file if it can't be read
    }

    const extension = file.split(".").pop();
    let language = extension;
    if (extension === "py") {
      language = "python";
    } else if (extension === "css") {
      language = "css";
    } else if (extension === "md" || extension === "mdx") {
      language = "markdown";
    } else if (extension === "tsx") {
      language = "typescript";
    } else if (extension === "yaml" || extension === "yml") {
      language = "yaml";
    } else if (extension === "toml") {
      language = "toml";
    }

    result[demo].files.push({
      name: file,
      content,
      path: file,
      language,
    });
  }
}

// Extract README content for config
for (const demo in result) {
  const readmeFile = result[demo].files.find(
    (file) => file.name === "README.mdx" || file.name === "README.md"
  );

  if (readmeFile) {
    result[demo].readmeContent = readmeFile.content;
  }
}

fs.writeFileSync(
  path.join(__dirname, "../src/files.json"),
  JSON.stringify(result, null, 2)
);

console.log(
  "Generated files.json with content from both feature and demo directories"
);
