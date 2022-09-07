

#include <iostream>
#include <vector>
#include <string>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

extern "C"
{
#include "solv/solver.h"
#include "solv/transaction.h"
#include "solv/repo_conda.h"
#include "solv/conda.h"
#include "solv/repo_solv.h"
#include "solv/pool.h"
}

namespace pyjs
{


    void transaction_to_txt(Transaction* transaction);

    class MPool
    {
    public:
        MPool();
        ~MPool();
        Pool* get();
        void load_repo(const std::string& fname, const std::string& url);
        py::dict solve(const std::vector<std::string>& match_specs);

        Pool* m_pool;
    };


    inline py::dict transaction_to_py(Transaction* transaction)
    {
        Pool* pool = transaction->pool;
        py::dict res;
        // res['DOWNGRADED'] = py::list();
        // res['UPGRADED'] = py::list();
        // res['CHANGED'] = py::list();
        // res['REINSTALLED'] = py::list();
        // res['ERASE'] = py::list();
        // res['INSTALL'] = py::list();
        // res['IGNORE'] = py::list();

        py::list remove_list;
        py::list install_list;

        res["REMOVE"] = remove_list;
        res["INSTALL"] = install_list;

        auto as_tuple = [&pool](Solvable* s)
        {
            const char* name = pool_id2str(pool, s->name);
            const char* evr = pool_id2str(pool, s->evr);
            const char* build_string;
            build_string = solvable_lookup_str(s, SOLVABLE_BUILDFLAVOR);
            return std::make_tuple(name, evr, build_string);
        };

        for (int i = 0; i < transaction->steps.count; i++)
        {
            Id p = transaction->steps.elements[i];
            Id ttype = transaction_type(transaction, p, SOLVER_TRANSACTION_SHOW_ALL);
            Solvable* s = pool_id2solvable(transaction->pool, p);
            Id i2;
            Solvable* s2;
            switch (ttype)
            {
                case SOLVER_TRANSACTION_DOWNGRADED:
                case SOLVER_TRANSACTION_UPGRADED:
                case SOLVER_TRANSACTION_CHANGED:
                case SOLVER_TRANSACTION_REINSTALLED:
                {
                    // std::cout << "Removing " << as_tuple(s) << std::endl;

                    remove_list.append(as_tuple(s));
                    s2 = transaction->pool->solvables + transaction_obs_pkg(transaction, p);
                    s2 = pool_id2solvable(pool, i2);
                    install_list.append(as_tuple(s));
                    break;
                }
                case SOLVER_TRANSACTION_ERASE:
                {
                    // std::cout << "Removing " << as_tuple(s) << std::endl;
                    remove_list.append(as_tuple(s));
                    break;
                }
                case SOLVER_TRANSACTION_INSTALL:
                {
                    // std::cout << "Installing " << as_tuple(s) << std::endl;
                    install_list.append(as_tuple(s));
                    break;
                }
                case SOLVER_TRANSACTION_IGNORE:
                    break;
                default:
                    std::cout << "Some weird case not handled" << std::endl;
                    break;
            }
        }
        return res;
    }


    MPool::MPool()
        : m_pool(pool_create())
    {
    }

    MPool::~MPool()
    {
        pool_free(m_pool);
    }

    Pool* MPool::get()
    {
        return m_pool;
    }

    void MPool::load_repo(const std::string& fname, const std::string& url)
    {
        FILE* f = fopen(fname.c_str(), "r");
        Repo* r = repo_create(m_pool, url.c_str());
        repo_add_conda(r, f, 0);
        fclose(f);

        // return r;
    }

    py::dict MPool::solve(const std::vector<std::string>& match_specs)
    {
        // std::cout << "Solving for ";
        // for (auto& el : match_specs)
        //     std::cout << el << " ";
        // std::cout << std::endl;

        Solver* s = solver_create(m_pool);

        Queue q;
        queue_init(&q);

        for (auto& spec : match_specs)
        {
            Id inst_id = pool_conda_matchspec(m_pool, spec.c_str());
            queue_push2(&q, SOLVER_INSTALL | SOLVER_SOLVABLE_PROVIDES, inst_id);
        }

        solver_solve(s, &q);

        bool success = solver_problem_count(s) == 0;
        Transaction* trans = solver_create_transaction(s);

        transaction_order(trans, 0);

        py::dict res = transaction_to_py(trans);

        transaction_free(trans);
        solver_free(s);
        queue_free(&q);
        return res;
    }


    void export_mamba(py::module_& m)
    {
        py::module_ m_internal = m.def_submodule("mamba", "mamba");


        py::class_<MPool>(m_internal, "MPool")
            .def(py::init<>())
            .def("solve",
                 [](MPool& pool, std::vector<std::string>& match_specs)
                 { return pool.solve(match_specs); })
            .def("load_repo", &MPool::load_repo);
    }

}  // end namspace pyjs
