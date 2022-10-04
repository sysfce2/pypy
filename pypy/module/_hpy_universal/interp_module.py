from rpython.rtyper.lltypesystem import lltype, rffi
from rpython.rlib.objectmodel import specialize
from pypy.interpreter.error import oefmt
from pypy.interpreter.executioncontext import ExecutionContext
from pypy.interpreter.module import Module, init_extra_module_attrs
from pypy.module._hpy_universal.apiset import API, DEBUG
from pypy.module._hpy_universal import interp_extfunc
from pypy.module._hpy_universal.state import State
from pypy.module._hpy_universal.interp_cpy_compat import attach_legacy_methods


@API.func("HPy HPyModule_Create(HPyContext *ctx, HPyModuleDef *def)")
def HPyModule_Create(space, handles, ctx, hpydef):
    return _hpymodule_create(handles, hpydef)

@DEBUG.func("HPy debug_HPyModule_Create(HPyContext *ctx, HPyModuleDef *def)",
            func_name='HPyModule_Create')
def debug_HPyModule_Create(space, handles, ctx, hpydef):
    state = State.get(space)
    assert ctx == state.get_handle_manager(debug=True).ctx
    return _hpymodule_create(handles, hpydef)

@specialize.arg(0)
def _hpymodule_create(handles, hpydef):
    space = handles.space
    modname = rffi.constcharp2str(hpydef.c_name)
    w_mod = Module(space, space.newtext(modname))
    #
    # add the functions defined in hpydef.c_legacy_methods
    if hpydef.c_legacy_methods:
        if space.config.objspace.hpy_cpyext_API:
            pymethods = rffi.cast(rffi.VOIDP, hpydef.c_legacy_methods)
            attach_legacy_methods(space, pymethods, w_mod, modname)
        else:
            raise oefmt(space.w_RuntimeError,
                "Module %s contains legacy methods, but _hpy_universal "
                "was compiled without cpyext support", modname)
    #
    # add the native HPy defines
    if hpydef.c_defines:
        p = hpydef.c_defines
        i = 0
        while p[i]:
            # hpy native methods
            hpymeth = p[i].c_meth
            name = rffi.constcharp2str(hpymeth.c_name)
            sig = rffi.cast(lltype.Signed, hpymeth.c_signature)
            doc = get_doc(hpymeth.c_doc)
            w_extfunc = handles.w_ExtensionFunction(
                space, handles, name, sig, doc, hpymeth.c_impl, w_mod)
            space.setattr(w_mod, space.newtext(w_extfunc.name), w_extfunc)
            i += 1
    if hpydef.c_doc:
        w_doc = space.newtext(rffi.constcharp2str(hpydef.c_doc))
    else:
        w_doc = space.w_None
    space.setattr(w_mod, space.newtext('__doc__'), w_doc)
    init_extra_module_attrs(space, w_mod)
    return handles.new(w_mod)

def get_doc(c_doc):
    if not c_doc:
        return None
    return rffi.constcharp2str(c_doc)


# In an different reality, we would be able to access the module and store
# the globals there. Instead, store them on the thread-local ExecutionContext
# like the exception state
ExecutionContext.hpy_globals = {}

@API.func("HPy HPyGlobal_Load(HPyContext *ctx, HPyGlobal global)")
def HPyGlobal_Load(space, handles, ctx, h_global):
    d_globals = space.getexecutioncontext().hpy_globals
    if h_global not in d_globals:
        raise oefmt(space.w_ValueError, "unknown HPyGlobal* in HPyGlobal_Load")
    return handles.new(d_globals[h_global])

@API.func("void HPyGlobal_Store(HPyContext *ctx, HPyGlobal *global, HPy h)")
def HPyGlobal_Store(space, handles, ctx, p_global, h_obj):
    if h_obj:
        w_obj = handles.deref(h_obj)
    else:
        w_obj = space.w_None
    # Release a potential already existing p_global[0]
    d_globals = space.getexecutioncontext().hpy_globals
    if p_global[0] in d_globals:
        d_globals.pop(p_global[0])
    d_globals[h_obj] = w_obj
    p_global[0] = h_obj
