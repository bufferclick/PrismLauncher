//! A Rust launcher's Horizon adapter.
//!
//! Two halves, and that is the whole port:
//!
//! 1. **The toolkit does the hard part.** `horizonport` verifies signatures,
//!    unpacks builds, prepares resources once and keeps the store. This adapter
//!    calls it with `--json` and reads the answer, so a Rust launcher shares the
//!    same audited implementation as a Node, C# or Python one.
//! 2. **The launcher starts the game itself**, with the Launch API
//!    (`docs/api/launch-reference.md`): the command comes from
//!    `horizonport play --dry-run`, the session JSON goes in on stdin, and the
//!    exit code says what happened.
//!
//! No process ever sees the access token: it is written to the child's stdin
//! and stdin is closed immediately.

use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};

use serde::{Deserialize, Serialize};

/// What `horizonport play --dry-run` prints: a validated command.
#[derive(Debug, Clone, Deserialize)]
pub struct LaunchPlan {
    pub argv: Vec<String>,
    pub cwd: PathBuf,
    pub instance: String,
    pub game: PathBuf,
    pub home: PathBuf,
    pub resources: PathBuf,
    pub session: String,
    #[serde(default)]
    pub env: std::collections::BTreeMap<String, String>,
}

/// The session JSON `horizon-client --session-stdin` reads.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    pub name: String,
    pub uuid: String,
    pub access_token: String,
    #[serde(default = "msa")]
    pub user_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub xuid: Option<String>,
}

fn msa() -> String {
    "msa".to_string()
}

/// One signed-in account, as this launcher keeps it (never in the game folder).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredAccount {
    pub name: String,
    pub uuid: String,
    pub owns: bool,
    /// Keep this in the OS keychain, not beside the others.
    pub refresh_token: String,
}

/// The exit codes Horizon promises (`docs/api/launch-reference.md`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HorizonExit {
    Quit,
    Error,
    Refused,
    Panicked,
    Other(i32),
}

impl HorizonExit {
    pub fn from_status(status: ExitStatus) -> Self {
        match status.code() {
            Some(0) => Self::Quit,
            Some(1) => Self::Error,
            Some(2) => Self::Refused,
            Some(101) => Self::Panicked,
            Some(other) => Self::Other(other),
            None => Self::Error,
        }
    }

    pub fn message(self) -> &'static str {
        match self {
            Self::Quit => "the player quit",
            Self::Error => "the game stopped on an error; a crash report was saved",
            Self::Refused => "the command line was refused; this is a bug in the launcher",
            Self::Panicked => "the game panicked; a crash report was saved",
            Self::Other(_) => "the game exited with an unexpected code",
        }
    }
}

/// Calls the toolkit and starts the game.
#[derive(Debug, Clone)]
pub struct HorizonPort {
    project: PathBuf,
    python: String,
    root: PathBuf,
}

#[derive(Debug)]
pub struct PortError {
    pub message: String,
    pub hint: String,
}

impl std::fmt::Display for PortError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for PortError {}

impl HorizonPort {
    /// `root` is the toolkit checkout (the folder holding `porting/`).
    pub fn new(project: impl Into<PathBuf>, root: impl Into<PathBuf>) -> Self {
        let python = if cfg!(windows) { "python" } else { "python3" }.to_string();
        Self { project: project.into(), python, root: root.into() }
    }

    /// Run one command and return its `--json` output.
    pub fn run(&self, args: &[&str]) -> Result<serde_json::Value, PortError> {
        let mut command = Command::new(&self.python);
        command
            .arg("-m")
            .arg("porting.horizonport")
            .arg("--json")
            .arg("--project")
            .arg(&self.project);
        command.args(args);
        command.current_dir(&self.root);
        let pythonpath = match std::env::var("PYTHONPATH") {
            Ok(existing) if !existing.is_empty() => format!("{}:{}", self.root.display(), existing),
            _ => self.root.display().to_string(),
        };
        command.env("PYTHONPATH", pythonpath);
        let output = command.output().map_err(|error| PortError {
            message: format!("could not run {}: {error}", self.python),
            hint: "Is python3 on PATH? `horizonport doctor` says what is missing.".into(),
        })?;
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let mut lines = stderr.lines().filter(|line| !line.trim().is_empty());
            let message = lines.next().unwrap_or("horizonport failed").trim_start_matches("error: ").to_string();
            return Err(PortError { message, hint: lines.collect::<Vec<_>>().join("\n") });
        }
        serde_json::from_slice(&output.stdout).map_err(|error| PortError {
            message: format!("horizonport printed something that is not JSON: {error}"),
            hint: String::new(),
        })
    }

    /// Install (or verify) the build the project pins.
    pub fn fetch(&self, tag: &str) -> Result<serde_json::Value, PortError> {
        self.run(&["fetch", "--tag", tag])
    }

    /// Prepare resources once for a build. `download` needs `session_file`.
    pub fn prepare(
        &self,
        build: &str,
        download: bool,
        session_file: Option<&Path>,
        server_jar: Option<&Path>,
    ) -> Result<serde_json::Value, PortError> {
        let mut args = vec!["prepare", "--build", build];
        if download {
            args.push("--download");
        }
        let session;
        if let Some(path) = session_file {
            session = path.display().to_string();
            args.extend(["--session", session.as_str()]);
        }
        let jar;
        if let Some(path) = server_jar {
            jar = path.display().to_string();
            args.extend(["--server-jar", jar.as_str()]);
        }
        self.run(&args)
    }

    /// Make the first instance: it reuses the prepared tree, so this takes seconds.
    pub fn add_instance(&self, name: &str, build: &str) -> Result<serde_json::Value, PortError> {
        self.run(&["instance", "new", name, "--build", build])
    }

    /// The validated command for an instance, without starting it.
    pub fn plan(&self, instance: &str) -> Result<LaunchPlan, PortError> {
        let value = self.run(&["play", instance, "--dry-run"])?;
        serde_json::from_value(value).map_err(|error| PortError {
            message: format!("the launch plan is not what this adapter expects: {error}"),
            hint: "Update the adapter with the toolkit (porting/PORTING.md, 'updating').".into(),
        })
    }
}

/// Start the game with `plan`, handing `session` over on stdin.
///
/// Returns the exit code, the crash report path (when the game wrote one) and
/// the tail of stderr for a launcher's "it crashed" panel.
pub fn launch(
    plan: &LaunchPlan,
    session: &Session,
) -> Result<(HorizonExit, Option<PathBuf>, String), PortError> {
    let (program, args) = plan.argv.split_first().ok_or_else(|| PortError {
        message: "the launch plan has no program".into(),
        hint: "The instance's build may not be installed.".into(),
    })?;
    let mut child = Command::new(program)
        .args(args)
        .current_dir(&plan.cwd)
        .envs(&plan.env)
        .stdin(Stdio::piped())
        .stdout(Stdio::inherit())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| PortError {
            message: format!("could not start {program}: {error}"),
            hint: "Check the instance's build: `horizonport check`.".into(),
        })?;
    {
        let stdin = child.stdin.as_mut().ok_or_else(|| PortError {
            message: "the game's stdin is closed".into(),
            hint: "Pass --session-stdin (the toolkit's plan does).".into(),
        })?;
        let json = serde_json::to_vec(session).map_err(|error| PortError {
            message: format!("the session is not writable as JSON: {error}"),
            hint: String::new(),
        })?;
        stdin.write_all(&json).and_then(|_| stdin.write_all(b"\n")).map_err(|error| PortError {
            message: format!("could not hand the session over: {error}"),
            hint: "The game may have exited immediately; run `horizonport play` in a terminal.".into(),
        })?;
    }
    let output = child.wait_with_output().map_err(|error| PortError {
        message: format!("waiting for the game failed: {error}"),
        hint: String::new(),
    })?;
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    Ok((HorizonExit::from_status(output.status), crash_report(&stderr), stderr))
}

/// The path in `Horizon: crash report saved to <path>`, when stderr has one.
pub fn crash_report(stderr: &str) -> Option<PathBuf> {
    const LINE: &str = "Horizon: crash report saved to ";
    stderr
        .lines()
        .filter_map(|line| line.strip_prefix(LINE))
        .next_back()
        .map(|path| PathBuf::from(path.trim()))
}

/// The session file a launcher writes when it can't use stdin (mode 0600).
pub fn write_session_file(path: &Path, session: &Session) -> std::io::Result<()> {
    let json = serde_json::to_vec(session)?;
    std::fs::write(path, json)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    }
    Ok(())
}
