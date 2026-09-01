; ModuleID = '/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/mmio_wrapper.c'
source_filename = "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/mmio_wrapper.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: nounwind uwtable
define dso_local void @wrapper_caller(ptr noundef %0) local_unnamed_addr #0 !dbg !14 {
  tail call void @llvm.dbg.value(metadata ptr %0, metadata !20, metadata !DIExpression()), !dbg !26
  call void @llvm.dbg.value(metadata ptr %0, metadata !27, metadata !DIExpression()), !dbg !33
  call void @llvm.dbg.value(metadata i32 16, metadata !32, metadata !DIExpression()), !dbg !33
  %2 = getelementptr inbounds i8, ptr %0, i64 16, !dbg !35
  call void @llvm.dbg.value(metadata ptr %2, metadata !36, metadata !DIExpression()), !dbg !46
  %3 = tail call i32 asm sideeffect "movl $1,$0", "=r,*m,~{memory},~{dirflag},~{fpsr},~{flags}"(ptr nonnull elementtype(i32) %2) #2, !dbg !48, !srcloc !49
  call void @llvm.dbg.value(metadata i32 %3, metadata !45, metadata !DIExpression()), !dbg !46
  tail call void @llvm.dbg.value(metadata i32 undef, metadata !21, metadata !DIExpression()), !dbg !26
  ret void, !dbg !50
}

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare void @llvm.dbg.value(metadata, metadata, metadata) #1

attributes #0 = { nounwind uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #1 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }
attributes #2 = { nounwind }

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!6, !7, !8, !9, !10, !11, !12}
!llvm.ident = !{!13}

!0 = distinct !DICompileUnit(language: DW_LANG_C11, file: !1, producer: "Ubuntu clang version 18.1.3 (1ubuntu1)", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug, retainedTypes: !2, splitDebugInlining: false, nameTableKind: None)
!1 = !DIFile(filename: "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/mmio_wrapper.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "eb0151c7fe8602a22dba47b1a7320003")
!2 = !{!3}
!3 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !4, size: 64)
!4 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: !5)
!5 = !DIBasicType(name: "unsigned int", size: 32, encoding: DW_ATE_unsigned)
!6 = !{i32 7, !"Dwarf Version", i32 5}
!7 = !{i32 2, !"Debug Info Version", i32 3}
!8 = !{i32 1, !"wchar_size", i32 4}
!9 = !{i32 8, !"PIC Level", i32 2}
!10 = !{i32 7, !"PIE Level", i32 2}
!11 = !{i32 7, !"uwtable", i32 2}
!12 = !{i32 7, !"debug-info-assignment-tracking", i1 true}
!13 = !{!"Ubuntu clang version 18.1.3 (1ubuntu1)"}
!14 = distinct !DISubprogram(name: "wrapper_caller", scope: !15, file: !15, line: 10, type: !16, scopeLine: 11, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !19)
!15 = !DIFile(filename: "qa/tests/fixtures/mmio_wrapper.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "eb0151c7fe8602a22dba47b1a7320003")
!16 = !DISubroutineType(types: !17)
!17 = !{null, !18}
!18 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: null, size: 64)
!19 = !{!20, !21}
!20 = !DILocalVariable(name: "base", arg: 1, scope: !14, file: !15, line: 10, type: !18)
!21 = !DILocalVariable(name: "value", scope: !14, file: !15, line: 12, type: !22)
!22 = !DIDerivedType(tag: DW_TAG_typedef, name: "u32", file: !23, line: 21, baseType: !24)
!23 = !DIFile(filename: "vendor/linux/include/asm-generic/int-ll64.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "12ca7bdb629352cc4c9a492f86b435a7")
!24 = !DIDerivedType(tag: DW_TAG_typedef, name: "__u32", file: !25, line: 27, baseType: !5)
!25 = !DIFile(filename: "vendor/linux/include/uapi/asm-generic/int-ll64.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "f4d0ec5bcdd84e825a78a7add39d54dd")
!26 = !DILocation(line: 0, scope: !14)
!27 = !DILocalVariable(name: "base", arg: 1, scope: !28, file: !15, line: 5, type: !18)
!28 = distinct !DISubprogram(name: "wrapper_read", scope: !15, file: !15, line: 5, type: !29, scopeLine: 6, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !31)
!29 = !DISubroutineType(types: !30)
!30 = !{!22, !18, !5}
!31 = !{!27, !32}
!32 = !DILocalVariable(name: "offset", arg: 2, scope: !28, file: !15, line: 5, type: !5)
!33 = !DILocation(line: 0, scope: !28, inlinedAt: !34)
!34 = distinct !DILocation(line: 12, column: 14, scope: !14)
!35 = !DILocation(line: 7, column: 20, scope: !28, inlinedAt: !34)
!36 = !DILocalVariable(name: "addr", arg: 1, scope: !37, file: !38, line: 59, type: !41)
!37 = distinct !DISubprogram(name: "readl", scope: !38, file: !38, line: 59, type: !39, scopeLine: 59, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !44)
!38 = !DIFile(filename: "vendor/linux/arch/x86/include/asm/io.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "7255a33f32535fc68bd0d1cd99111699")
!39 = !DISubroutineType(types: !40)
!40 = !{!5, !41}
!41 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !42, size: 64)
!42 = !DIDerivedType(tag: DW_TAG_const_type, baseType: !43)
!43 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: null)
!44 = !{!36, !45}
!45 = !DILocalVariable(name: "ret", scope: !37, file: !38, line: 59, type: !5)
!46 = !DILocation(line: 0, scope: !37, inlinedAt: !47)
!47 = distinct !DILocation(line: 7, column: 9, scope: !28, inlinedAt: !34)
!48 = !DILocation(line: 59, column: 1, scope: !37, inlinedAt: !47)
!49 = !{i64 2149611328}
!50 = !DILocation(line: 15, column: 1, scope: !14)
