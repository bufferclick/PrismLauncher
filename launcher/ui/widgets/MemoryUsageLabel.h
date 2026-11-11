// SPDX-License-Identifier: GPL-3.0-only
/*
 *  JL - Minecraft Launcher
 *  Copyright (C) 2026 Buffer (JLac)
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#pragma once

#include <QElapsedTimer>
#include <QLabel>

class QProcess;

/**
 * Shows the live heap usage of the game process, in the style of the F3 memory readout.
 *
 * A JVM cannot be asked for its live heap from the outside without an agent, so this
 * reads what the game itself reports:
 *
 *  - the `-Xmx` value the launcher passed on the command line (the maximum), and
 *  - `Memory: <used> / <total>` lines, which vanilla prints on the F3 screen and which
 *    are also scraped from the log when present.
 *
 * Until a sample arrives it shows the configured maximum. The figure is a heap reading,
 * not process RSS: it is what the game itself considers "used".
 */
class MemoryUsageLabel : public QLabel {
    Q_OBJECT

   public:
    explicit MemoryUsageLabel(QWidget* parent = nullptr);

    /// \brief Set the configured heap ceiling, in MiB (the instance's MaxMemAlloc).
    void setMaxMiB(int mib);

    /// \brief The heap max in MiB, or 0 if the arguments did not set one.
    int maxMiB() const { return m_maxMiB; }

    /// \brief Feed one line of game output; returns true if it produced a sample.
    bool handleLogLine(const QString& line);

    /// \brief Forget the last sample (e.g. when the game stops).
    void reset();

   private:
    void updateText();

    QElapsedTimer m_lastSample;
    int m_maxMiB = 0;
    int m_usedMiB = -1;
    int m_totalMiB = -1;
};
