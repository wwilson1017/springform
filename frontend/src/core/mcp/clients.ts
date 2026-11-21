// How each AI tool is pointed at an MCP link (docs/agents/mcp.md §1). Lifted from todo-gtd's
// `clients.ts` (docs/PROVENANCE.md). The link is a complete credential in a URL (no header, no
// sign-in), so every recipe is "use the link as the server URL".

/** The name the link is registered under in a tool's own server list. */
const SERVER_NAME = 'springform';

export interface ClientSetup {
  /** The tab label. */
  name: string;
  /** One-click install address, for the tools with a documented URL scheme. */
  deeplink?: (url: string) => string;
  /** A command or config snippet to paste, with the link filled in. */
  command?: (url: string) => string;
  /** Where the snippet goes, when it is not a terminal command. */
  commandLabel?: string;
  /** Click path for the chat apps; the last step is always "paste the link". */
  steps?: string[];
  /** Plan or region limits worth knowing before starting. */
  note?: string;
}

export const CLIENTS: ClientSetup[] = [
  {
    name: 'Claude',
    steps: [
      'In claude.ai or Claude Desktop, open Customize → Connectors.',
      'Choose “Add custom connector”.',
      'Paste the link as the remote MCP server URL and choose Add. Leave the sign-in fields empty.',
    ],
  },
  {
    name: 'ChatGPT',
    steps: [
      'Go to chatgpt.com/plugins, select the plus button, then “Add custom MCP server”.',
      'Give it a name, paste the link as the Server URL, choose “No authentication”, accept the warning and select “Create as a plugin”.',
    ],
    note: 'Paid plans, on the web. Install the new plugin, then pick it with @ in a chat.',
  },
  {
    name: 'Gemini',
    steps: [
      'On a computer, open gemini.google.com → Settings → Connected Apps.',
      'Under “Custom apps”, choose “Add a custom app”.',
      'Paste the link as the MCP server URL and follow the prompts.',
    ],
    note: 'US only, personal Google accounts, with Keep Activity on.',
  },
  {
    name: 'Claude Code',
    command: (url) => `claude mcp add --transport http ${SERVER_NAME} ${url}`,
  },
  {
    name: 'Cursor',
    // config = base64 of the inner server object.
    deeplink: (url) =>
      `cursor://anysphere.cursor-deeplink/mcp/install?name=${SERVER_NAME}` +
      `&config=${encodeURIComponent(btoa(JSON.stringify({ url })))}`,
    command: (url) => JSON.stringify({ mcpServers: { [SERVER_NAME]: { url } } }),
    commandLabel: 'Or add to ~/.cursor/mcp.json',
  },
  {
    name: 'VS Code',
    deeplink: (url) =>
      `vscode:mcp/install?${encodeURIComponent(JSON.stringify({ name: SERVER_NAME, type: 'http', url }))}`,
    command: (url) => `code --add-mcp '${JSON.stringify({ name: SERVER_NAME, type: 'http', url })}'`,
    commandLabel: 'Or run in a terminal',
  },
  {
    name: 'Codex',
    command: (url) => `codex mcp add ${SERVER_NAME} --url ${url}`,
  },
  {
    name: 'Gemini CLI',
    command: (url) => `gemini mcp add --transport http ${SERVER_NAME} ${url}`,
  },
];
