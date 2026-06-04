const fs = require("fs");
const path = require("path");
const vscode = require("vscode");

function getResultsPaths() {
  const firstFolder = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
  if (!firstFolder || !firstFolder.uri || !firstFolder.uri.fsPath) {
    return null;
  }

  const workspaceRoot = firstFolder.uri.fsPath;
  const resultsDir = path.join(workspaceRoot, "code", "prototype_v1", "results");
  return {
    resultsDir,
    outputPath: path.join(resultsDir, "active_editor_state.json"),
    tmpPath: path.join(resultsDir, "active_editor_state.tmp.json"),
  };
}

function getWorkspaceName() {
  if (vscode.workspace.name) {
    return vscode.workspace.name;
  }

  const firstFolder = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
  return firstFolder ? firstFolder.name : "no-workspace";
}

function buildPayload(editor, eventType) {
  const document = editor && editor.document;
  const activeFilePath = document && document.uri ? document.uri.fsPath : "";

  return {
    active_file_path: activeFilePath,
    active_file_name: activeFilePath ? path.basename(activeFilePath) : "",
    language_id: document ? document.languageId : "",
    is_dirty: document ? Boolean(document.isDirty) : false,
    workspace_name: getWorkspaceName(),
    timestamp: new Date().toISOString(),
    event_type: eventType,
  };
}

function writePayload(payload) {
  const paths = getResultsPaths();
  if (!paths) {
    return;
  }

  fs.mkdirSync(paths.resultsDir, { recursive: true });
  fs.writeFileSync(paths.tmpPath, JSON.stringify(payload, null, 2), "utf8");
  try {
    fs.rmSync(paths.outputPath, { force: true });
  } catch (_error) {
    // Best-effort cleanup before rename on Windows.
  }
  fs.renameSync(paths.tmpPath, paths.outputPath);
}

function writeActiveEditorState(eventType, editor = vscode.window.activeTextEditor) {
  writePayload(buildPayload(editor, eventType));
}

function sameDocument(left, right) {
  if (!left || !right || !left.uri || !right.uri) {
    return false;
  }
  return left.uri.toString() === right.uri.toString();
}

function activate(context) {
  writeActiveEditorState("extension_activated");

  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      writeActiveEditorState("active_editor_changed", editor);
    }),
  );

  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((document) => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || !sameDocument(editor.document, document)) {
        return;
      }
      writeActiveEditorState("document_saved", editor);
    }),
  );

  context.subscriptions.push(
    vscode.workspace.onDidChangeTextDocument((event) => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || !sameDocument(editor.document, event.document)) {
        return;
      }
      writeActiveEditorState("document_changed", editor);
    }),
  );
}

function deactivate() {}

module.exports = {
  activate,
  deactivate,
};