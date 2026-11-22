#!/usr/bin/env python3
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

APPLIED = "applied"
SKIPPED = "skipped"
FAILED = "failed"
WARNED = "warned"


def read(path):
    return path.read_text(encoding="utf-8")


def write(path, text):
    path.write_text(text, encoding="utf-8")


def replace_once(path, old, new, marker, label, required=True):
    if not path.is_file():
        print(f"[{label}] {path} not found", file=sys.stderr)
        return FAILED if required else WARNED
    text = read(path)
    if marker in text:
        print(f"[{label}] already applied")
        return SKIPPED
    if text.count(old) != 1:
        print(f"[{label}] expected block found {text.count(old)} times in {path.name}, not touching it", file=sys.stderr)
        return FAILED if required else WARNED
    write(path, text.replace(old, new, 1))
    print(f"[{label}] applied")
    return APPLIED


def ios_visibility(root):
    exported = """

    set(MOBILEGL_IOS_EXPORTED_SYMBOLS
        "${CMAKE_CURRENT_SOURCE_DIR}/MobileGL/MG_Impl/DyldInterpose/ExportedSymbols.txt")
    target_link_options(${CMAKE_PROJECT_NAME} PRIVATE
        "LINKER:-exported_symbols_list,${MOBILEGL_IOS_EXPORTED_SYMBOLS}")
    set_property(TARGET ${CMAKE_PROJECT_NAME} APPEND PROPERTY
        LINK_DEPENDS "${MOBILEGL_IOS_EXPORTED_SYMBOLS}")"""
    # newest layout first (module targets, one shared interface target), then the older one
    candidates = [
        """if (APPLE AND MOBILEGL_IOS)
    target_compile_definitions(mgl_build_iface INTERFACE MOBILEGL_IOS=1 _LIBCPP_DISABLE_AVAILABILITY)""",
        """if (APPLE AND MOBILEGL_IOS)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PUBLIC MOBILEGL_IOS=1 _LIBCPP_DISABLE_AVAILABILITY)""",
    ]
    target = root / "CMakeLists.txt"
    if not target.is_file():
        print(f"[ios_visibility] {target} not found", file=sys.stderr)
        return FAILED
    text = read(target)
    if "MOBILEGL_IOS_EXPORTED_SYMBOLS" in text:
        print("[ios_visibility] already applied")
        return SKIPPED
    for old in candidates:
        if text.count(old) == 1:
            write(target, text.replace(old, old + exported, 1))
            print("[ios_visibility] applied")
            return APPLIED
    print("[ios_visibility] no known iOS block found in CMakeLists.txt, not touching it", file=sys.stderr)
    return FAILED


def ios_resolution(root):
    # Resolution slider: the game renders into a smaller fbo and blits it to the window with a
    # destination rect of that same smaller size, so it would only fill a corner of the swapchain.
    # When a color blit to the default framebuffer has equal source/destination sizes that differ
    # from the swapchain, stretch the destination over the whole swapchain and let the blit scale.
    marker = "isFullscreenScaledBlit"

    # Newest layout (wire arm): BlitWireFramebuffers(sx0..dy1, mask, filter) in WireFramebuffer.cpp.
    # The rect parameters are plain by-value GLints, so they can be rewritten before the blit lambda.
    wire_old = """        if (!read || !draw) MagmaWireFatal("blit-framebuffer-record");
        state.VerbBlitNamedConsumed = named;
"""
    wire_new = wire_old + """        // resolution slider: the source fbo is smaller but the dst rect can end up the same size,
        // so stretch it over the whole swapchain and let the blit scale it
        if (draw->IsDefault && !read->IsDefault && (mask & GL_COLOR_BUFFER_BIT) != 0) {
            const VkExtent2D framebufferExtent = m_swapchainObject.GetExtent();
            const GLint requestedSrcWidth = std::abs(sx1 - sx0);
            const GLint requestedSrcHeight = std::abs(sy1 - sy0);
            const GLint requestedDstWidth = std::abs(dx1 - dx0);
            const GLint requestedDstHeight = std::abs(dy1 - dy0);

            const Bool isFullscreenScaledBlit =
                requestedSrcWidth > 0 &&
                requestedSrcHeight > 0 &&
                requestedDstWidth == requestedSrcWidth &&
                requestedDstHeight == requestedSrcHeight &&
                (requestedDstWidth != static_cast<GLint>(framebufferExtent.width) ||
                 requestedDstHeight != static_cast<GLint>(framebufferExtent.height));

            if (isFullscreenScaledBlit) {
                dx0 = 0;
                dy0 = 0;
                dx1 = static_cast<GLint>(framebufferExtent.width);
                dy1 = static_cast<GLint>(framebufferExtent.height);
            }
        }
"""

    # Older layout: the VkImageBlit lived in VulkanRenderer.cpp (pinned commits before the wire split).
    legacy_old = """        VkImageBlit blitRegion{};
        blitRegion.srcSubresource.aspectMask = srcBinding.aspectMask;"""
    legacy_new = """        // resolution slider: the source fbo is smaller but the dst rect can end up the same size,
        // so stretch it over the whole swapchain and let the blit scale it
        if (drawIsDefaultFbo) {
            const Int requestedSrcWidth = std::abs(srcX1 - srcX0);
            const Int requestedSrcHeight = std::abs(srcY1 - srcY0);
            const Int requestedDstWidth = std::abs(dstX1 - dstX0);
            const Int requestedDstHeight = std::abs(dstY1 - dstY0);

            const Uint32 framebufferWidth = dstBinding.extent.x();
            const Uint32 framebufferHeight = dstBinding.extent.y();

            const Bool isFullscreenScaledBlit =
                requestedSrcWidth > 0 &&
                requestedSrcHeight > 0 &&
                requestedDstWidth == requestedSrcWidth &&
                requestedDstHeight == requestedSrcHeight &&
                (requestedDstWidth != static_cast<Int>(framebufferWidth) ||
                 requestedDstHeight != static_cast<Int>(framebufferHeight));

            if (isFullscreenScaledBlit) {
                dstX0 = 0;
                dstY0 = 0;
                dstX1 = static_cast<GLint>(framebufferWidth);
                dstY1 = static_cast<GLint>(framebufferHeight);
            }
        }

        VkImageBlit blitRegion{};
        blitRegion.srcSubresource.aspectMask = srcBinding.aspectMask;"""

    renderer_dir = root / "MobileGL/MG_Backend/DirectVulkan/Renderer"
    files = sorted(renderer_dir.glob("*.cpp")) if renderer_dir.is_dir() else []
    texts = {p: read(p) for p in files}

    if any(marker in t for t in texts.values()):
        print("[ios_resolution] already applied")
        return SKIPPED

    for label, old, new in (("wire", wire_old, wire_new), ("legacy", legacy_old, legacy_new)):
        holders = [p for p, t in texts.items() if t.count(old) == 1]
        if len(holders) == 1:
            write(holders[0], texts[holders[0]].replace(old, new, 1))
            print(f"[ios_resolution] applied ({label} layout) in {holders[0].name}")
            return APPLIED

    blit_files = [p.name for p, t in texts.items() if "VkImageBlit" in t]
    print("[ios_resolution] neither the wire nor the legacy blit block was found, not touching anything. "
          f"Files that mention VkImageBlit: {', '.join(blit_files) or 'none'}", file=sys.stderr)
    return FAILED


def hash_shim(root):
    shim_rel = "MobileGL/MG_Util/Compat/libcxx_hash_shim.cpp"
    anchor = "MobileGL/MG_Util/Debug/Log.cpp"

    src = HERE / "libcxx_hash_shim.cpp"
    dst = root / shim_rel
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        print("[hash_shim] copied libcxx_hash_shim.cpp")
    elif not dst.is_file():
        print(f"[hash_shim] {src} missing and {shim_rel} not in the checkout", file=sys.stderr)
        return FAILED

    target = root / "CMakeLists.txt"
    if not target.is_file():
        print(f"[hash_shim] {target} not found", file=sys.stderr)
        return FAILED
    text = read(target)
    if shim_rel in text:
        print("[hash_shim] cmake entry already there")
        return SKIPPED
    if anchor not in text:
        print(f"[hash_shim] anchor {anchor} not in CMakeLists.txt, upstream moved it", file=sys.stderr)
        return FAILED

    out = []
    done = False
    for line in text.splitlines(keepends=True):
        out.append(line)
        if not done and anchor in line:
            out.append(f"\n    {shim_rel}\n")
            done = True
    write(target, "".join(out))
    print("[hash_shim] applied")
    return APPLIED


def enable_availability(root):
    target = root / "CMakeLists.txt"
    if not target.is_file():
        print(f"[enable_availability] {target} not found", file=sys.stderr)
        return FAILED
    text = read(target)
    if "_LIBCPP_DISABLE_AVAILABILITY" not in text:
        print("[enable_availability] already applied")
        return SKIPPED
    pattern = re.compile(
        r"(target_compile_definitions\((?:\$\{CMAKE_PROJECT_NAME\}(?:_s)?|mgl_build_iface) "
        r"(?:PUBLIC|INTERFACE) MOBILEGL_IOS=1) _LIBCPP_DISABLE_AVAILABILITY(\))")
    text, count = pattern.subn(r"\1\2", text)
    if count == 0:
        print("[enable_availability] pattern not found, CMakeLists.txt changed upstream", file=sys.stderr)
        return FAILED
    write(target, text)
    print(f"[enable_availability] applied to {count} target(s)")
    return APPLIED


def glslang(root):
    target = root / "3rdparty/glslang/SPIRV/GlslangToSpv.cpp"
    old = """// Convert a glslang AST swizzle node to a swizzle vector for building SPIR-V.
void TGlslangToSpvTraverser::convertSwizzle(const glslang::TIntermAggregate& node, std::vector<unsigned>& swizzle)
{
    const glslang::TIntermSequence& swizzleSequence = node.getSequence();
    for (int i = 0; i < (int)swizzleSequence.size(); ++i)
        swizzle.push_back(swizzleSequence[i]->getAsConstantUnion()->getConstArray()[0].getIConst());
}"""
    new = """// Convert a glslang AST swizzle node to a swizzle vector for building SPIR-V.
void TGlslangToSpvTraverser::convertSwizzle(const glslang::TIntermAggregate& node, std::vector<unsigned>& swizzle)
{
    const glslang::TIntermSequence& swizzleSequence = node.getSequence();
    for (int i = 0; i < (int)swizzleSequence.size(); ++i) {
        // non-constant index node used to null deref and kill the whole jvm, fall back to .x instead
        const glslang::TIntermConstantUnion* constUnion = swizzleSequence[i]->getAsConstantUnion();
        if (constUnion == nullptr) {
            fprintf(stderr, "[glslang] convertSwizzle: non-constant swizzle index element %d, using component 0\\n", i);
            swizzle.push_back(0);
            continue;
        }
        swizzle.push_back(constUnion->getConstArray()[0].getIConst());
    }
}"""
    return replace_once(target, old, new, "using component 0", "glslang", required=False)


def log_to_stderr(root):
    old = """            WriteToFile(out.c_str());

            va_end(args);"""
    new = """#if defined(MOBILEGL_IOS)
            // warnings and up also go to stderr so they land in latestlog.txt, MOBILEGL_LOG_CONSOLE=1 sends everything
            static const bool mirrorAll = std::getenv("MOBILEGL_LOG_CONSOLE") != nullptr;
            static int mirrored = 0;
            if (mirrorAll || (mirrored < 2000 && (levelTag[0] == 'W' || levelTag[0] == 'E' || levelTag[0] == 'F'))) {
                mirrored++;
                std::fputs(out.c_str(), stderr);
            }
#endif
            WriteToFile(out.c_str());

            va_end(args);"""
    target = root / "MobileGL/MG_Util/Debug/Log.cpp"
    return replace_once(target, old, new, "MOBILEGL_LOG_CONSOLE", "log_to_stderr", required=False)


def qualify_definitions(root):
    # glGetAttachedObjectsARB in GLImpl/Exporting/Definitions.cpp spells Vector and SizeT without
    # the MobileGL:: prefix, and in this build nothing brings those names into scope there. Qualify
    # them so the file compiles. Harmless if upstream already did.
    target = root / "MobileGL/MG_Impl/GLImpl/Exporting/Definitions.cpp"
    if not target.is_file():
        print(f"[qualify_definitions] {target} not found, nothing to do")
        return SKIPPED
    text = read(target)
    old_a = "Vector<GLuint> names(maxCount > 0 ? static_cast<SizeT>(maxCount) : 0);"
    new_a = "MobileGL::Vector<GLuint> names(maxCount > 0 ? static_cast<MobileGL::SizeT>(maxCount) : 0);"
    old_b = "names[static_cast<SizeT>(i)]"
    new_b = "names[static_cast<MobileGL::SizeT>(i)]"
    if old_a not in text and old_b not in text:
        print("[qualify_definitions] already qualified or changed upstream, not touching it")
        return SKIPPED
    n_a, n_b = text.count(old_a), text.count(old_b)
    if n_a != 1 or n_b != 1:
        print(f"[qualify_definitions] expected one of each line, found {n_a} and {n_b}; not touching it", file=sys.stderr)
        return WARNED
    write(target, text.replace(old_a, new_a, 1).replace(old_b, new_b, 1))
    print("[qualify_definitions] applied")
    return APPLIED


STEPS = [
    ("ios_visibility", ios_visibility, True),
    ("ios_resolution", ios_resolution, True),
    ("hash_shim", hash_shim, True),
    ("enable_availability", enable_availability, True),
    ("glslang", glslang, False),
    ("log_to_stderr", log_to_stderr, False),
    ("qualify_definitions", qualify_definitions, False),
]


def main():
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-mobilegl-checkout>", file=sys.stderr)
        return 1

    root = Path(sys.argv[1]).resolve()
    if not (root / "CMakeLists.txt").is_file():
        print(f"{root} doesn't look like a MobileGL checkout", file=sys.stderr)
        return 1

    failed = []
    for name, step, required in STEPS:
        try:
            result = step(root)
        except Exception as e:
            print(f"[{name}] crashed: {e}", file=sys.stderr)
            result = FAILED if required else WARNED
        if result == FAILED:
            failed.append(name)

    if failed:
        print("patch_mobilegl: failed steps: " + ", ".join(failed), file=sys.stderr)
        return 1
    print("patch_mobilegl: done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
