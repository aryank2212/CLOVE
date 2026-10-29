// CLOVE runs without a console window: CLOVE is the whole UI.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    clove_lib::run()
}
