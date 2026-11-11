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

#include <QString>

/**
 * Collects a diagnostic report describing the machine JL is running on.
 *
 * This exists so a maintainer can see what the launcher sees without access to the
 * machine. Everything here is read-only and local; nothing is uploaded anywhere. The
 * output is a plain-text report meant to be copied or saved and shared by hand.
 *
 * Keep it honest: report what was measured and what could not be measured, never a
 * guess dressed up as a fact.
 */
namespace DebugReport {

/// \brief Build the full report. May take a few hundred ms (process/GPU queries).
QString collect();

/// \brief Default filename for the "Save report" button.
QString suggestedFileName();

}  // namespace DebugReport
