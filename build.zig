const std = @import("std");

pub fn build(b: *std.Build) void {
    b.installFile("bin/texmini", "bin/texmini");
    b.installFile("src/texmini/__init__.py", "src/texmini/__init__.py");
    b.installFile("src/texmini/cli.py", "src/texmini/cli.py");
}
