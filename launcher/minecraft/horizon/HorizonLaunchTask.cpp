// SPDX-License-Identifier: GPL-3.0-only
/*
 *  Prism Launcher - Minecraft Launcher
 *  Copyright (C) 2026 JL contributors
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "HorizonLaunchTask.h"

#include <QDebug>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>

#include "HorizonInstance.h"
#include "HorizonPort.h"
#include "MessageLevel.h"

namespace {
// The Launch API's exit codes (docs/api/launch.md).
constexpr int kExitQuit = 0;
constexpr int kExitError = 1;
constexpr int kExitRefused = 2;
constexpr int kExitPanic = 101;

// "Horizon: crash report saved to <path>" is the last line the game writes
// when it has a crash report for us.
const QString kCrashLine = QStringLiteral("Horizon: crash report saved to ");
}  // namespace

HorizonLaunchTask* HorizonLaunchTask::create(HorizonInstance* instance, AuthSessionPtr session)
{
    auto* task = new HorizonLaunchTask(instance, session);
    task->init();
    return task;
}

HorizonLaunchTask::HorizonLaunchTask(HorizonInstance* instance, AuthSessionPtr session) : LaunchTask(instance), m_session(std::move(session))
{
    // No LaunchStep chain: Horizon is not a JVM launch, and the toolkit builds
    // and validates the command for us. `executeTask` below is the whole flow.
}

HorizonInstance* HorizonLaunchTask::horizonInstance() const
{
    return static_cast<HorizonInstance*>(m_instance);
}

QStringList HorizonLaunchTask::planArguments() const
{
    return { "play", horizonInstance()->name(), "--dry-run", "--width",  QString::number(horizonInstance()->settings()->get("LaunchMaximized").toBool() ? 1920 : 1280),
             "--height", "720" };
}

void HorizonLaunchTask::executeTask()
{
    m_instance->setRunning(true);
    m_instance->setCrashed(false);

    QString error;
    if (!HorizonPort::ensureProject(&error)) {
        m_instance->setRunning(false);
        emitFailed(error);
        return;
    }

    if (!m_session || m_session->access_token.isEmpty()) {
        m_instance->setRunning(false);
        emitFailed(tr("Horizon needs a Microsoft account that owns Minecraft: Java Edition. "
                      "Add one in Accounts, then press Play again."));
        return;
    }

    onLogLine(tr("Preparing the launch command for %1 (%2)").arg(m_instance->name(), horizonInstance()->buildTag()),
              MessageLevel::Launcher);

    QJsonObject plan;
    if (!HorizonPort::run(planArguments(), &plan, &error, 300000)) {
        m_instance->setRunning(false);
        // The toolkit's own message already says what to do (fetch/prepare).
        emitFailed(error);
        return;
    }
    startGame(plan);
}

void HorizonLaunchTask::startGame(const QJsonObject& plan)
{
    const auto argv = plan.value("argv").toArray();
    if (argv.isEmpty()) {
        m_instance->setRunning(false);
        emitFailed(tr("The toolkit returned no command to run."));
        return;
    }

    QStringList program;
    for (const auto& value : argv)
        program << value.toString();
    const QString executable = program.takeFirst();
    const QString workingDirectory = plan.value("cwd").toString();

    onLogLine(tr("Starting: %1 %2").arg(executable, program.join(' ')), MessageLevel::Launcher);

    auto* process = new QProcess(this);
    process->setWorkingDirectory(workingDirectory);
    process->setProcessChannelMode(QProcess::SeparateChannels);
    connect(process, &QProcess::readyReadStandardError, this, [this, process] {
        const QString text = QString::fromUtf8(process->readAllStandardError());
        m_stdErr += text;
        const auto lines = text.split('\n', Qt::SkipEmptyParts);
        for (const auto& line : lines)
            onLogLine(line, MessageLevel::Error);
    });
    connect(process, &QProcess::readyReadStandardOutput, this, [this, process] {
        const auto lines = QString::fromUtf8(process->readAllStandardOutput()).split('\n', Qt::SkipEmptyParts);
        for (const auto& line : lines)
            onLogLine(line, MessageLevel::Message);
    });
    connect(process, &QProcess::errorOccurred, this, [this, process](QProcess::ProcessError processError) {
        if (processError == QProcess::FailedToStart) {
            m_running = false;
            m_instance->setRunning(false);
            emitFailed(tr("Could not start Horizon: %1").arg(process->errorString()));
        }
    });
    connect(process, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished), this,
            [this](int exitCode, QProcess::ExitStatus status) {
                m_running = false;
                m_instance->setRunning(false);
                reportExit(exitCode, m_stdErr);
                Q_UNUSED(status);
            });

    m_running = true;
    emit readyForLaunch();
    process->start(executable, program);
    if (!process->waitForStarted(30000)) {
        m_running = false;
        m_instance->setRunning(false);
        emitFailed(tr("Could not start Horizon: %1").arg(process->errorString()));
        return;
    }

    // The session goes in on stdin and stdin is closed immediately. Nothing
    // touches the disk, argv or the environment.
    QJsonObject session;
    session.insert("name", m_session->player_name);
    session.insert("uuid", m_session->uuid);
    session.insert("access_token", m_session->access_token);
    session.insert("user_type", m_session->user_type.isEmpty() ? QStringLiteral("msa") : m_session->user_type);
    process->write(QJsonDocument(session).toJson(QJsonDocument::Compact) + "\n");
    process->closeWriteChannel();
}

void HorizonLaunchTask::reportExit(int code, const QString& stdErrText)
{
    if (code == kExitQuit) {
        onLogLine(tr("Horizon closed."), MessageLevel::Launcher);
        emitSucceeded();
        return;
    }

    // The last crash-report line on stderr is the authoritative path.
    QString crashReport;
    for (const auto& line : stdErrText.split('\n')) {
        if (line.startsWith(kCrashLine))
            crashReport = line.mid(kCrashLine.size()).trimmed();
    }

    if (code == kExitRefused) {
        // Exit 2 means the launcher asked for an option the build does not
        // take. That is our bug, not a crash, and it must be logged as such.
        m_instance->setCrashed(true);
        emitFailed(tr("Horizon refused the command line (exit 2). This is a bug in JL, not a crash: "
                      "the build does not accept one of the options the toolkit passed. "
                      "Please report it with the log."));
        return;
    }

    m_instance->setCrashed(true);
    QString message;
    if (code == kExitPanic)
        message = tr("Horizon panicked and stopped.");
    else if (code == kExitError)
        message = tr("Horizon stopped on an error.");
    else
        message = tr("Horizon exited with code %1.").arg(code);

    if (!crashReport.isEmpty())
        message += QStringLiteral("\n\n") + tr("Crash report: %1").arg(crashReport);
    else if (!stdErrText.trimmed().isEmpty())
        message += QStringLiteral("\n\n") + stdErrText.trimmed().split('\n').last();

    emitFailed(message);
}

bool HorizonLaunchTask::abort()
{
    if (!m_running)
        return false;
    // The game owns its window; closing it is the player's call. We stop
    // waiting, which is what "abort" means for a launch task.
    emitAborted();
    return true;
}

bool HorizonLaunchTask::canAbort() const
{
    return m_running;
}
